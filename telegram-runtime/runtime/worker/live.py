"""Live Telethon side of the worker: session connect, SendTransport impl,
and update->event_inbox ingress (§4.2/§4.3).

Isolation model: one TelethonTransport + one TelegramClient per account,
keyed by account uuid. Every send path funnels through the executor's
SendPolicy gate upstream; this layer only maps Telegram outcomes into the
§8.3 error taxonomy and feeds the LiveRegistry the policy gate reads.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from telethon import TelegramClient, events, utils
from telethon.errors import (
    AuthKeyUnregisteredError,
    ChannelPrivateError,
    ChatWriteForbiddenError,
    FloodWaitError,
    MessageEmptyError,
    PeerIdInvalidError,
    SessionRevokedError,
    SlowModeWaitError,
    UnauthorizedError,
    UserBannedInChannelError,
)
from telethon.sessions import SQLiteSession
from telethon.tl import types as tl

from runtime.delivery.executor import SendTransport, TransportError, TransportErrorKind
from runtime.delivery.policy import LiveAccount, SendState
from runtime.ingest.normalizer import ChatClass, EventNormalizer, RawUpdate
from runtime.planner.model import CloneMode, DeliveryPlan, EventKind
from runtime.storage.repos import EventInboxRepository
from runtime.worker.control_client import ControlClient, SessionBundle

log = logging.getLogger(__name__)


class LiveRegistry:
    """Per-account live state the SendPolicy gate reads (deps.live).

    Transport errors and commands mutate it; runner halts consume it."""

    def __init__(self) -> None:
        self._rows: dict[str, LiveAccount] = {}

    def register(self, account_id: str, generation: int) -> None:
        self._rows[account_id] = LiveAccount(
            account_id=account_id, generation=generation,
            send_state=SendState.SENDABLE)

    def get(self, account_id: str) -> LiveAccount:
        return self._rows.get(
            account_id,
            LiveAccount(account_id=account_id, generation=-1,
                        send_state=SendState.AUTH_DEAD),
        )

    def mark_paused(self, account_id: str) -> None:
        self._set(account_id, send_state=SendState.PAUSED)

    def mark_resumed(self, account_id: str) -> None:
        self._set(account_id, send_state=SendState.SENDABLE,
                  flood_wait_until=None)

    def mark_auth_dead(self, account_id: str) -> None:
        self._set(account_id, send_state=SendState.AUTH_DEAD)

    def mark_flood_wait(self, account_id: str, until: float) -> None:
        self._set(account_id, send_state=SendState.FLOOD_WAIT,
                  flood_wait_until=until)

    def drop(self, account_id: str) -> None:
        self._rows.pop(account_id, None)

    def _set(self, account_id: str, **kw) -> None:
        cur = self._rows.get(account_id)
        if cur is not None:
            self._rows[account_id] = LiveAccount(
                account_id=cur.account_id,
                generation=kw.get("generation", cur.generation),
                send_state=kw.get("send_state", cur.send_state),
                flood_wait_until=kw.get("flood_wait_until",
                                        cur.flood_wait_until),
            )


class PayloadResolver:
    """payload_ref -> sendable text.

    'candidate:{uuid}' resolves through the control plane and is hash-bound:
    the content fetched must sha256-match the job's payload_hash — sending
    anything else is a policy violation (§10.1)."""

    def __init__(self, control: ControlClient):
        self._control = control

    async def candidate_text(self, uuid: str, expected_hash: str | None) -> str:
        cand = await self._control.get_candidate(uuid)
        if cand.status != "approved":
            raise TransportError(TransportErrorKind.CONTENT,
                                 f"candidate {uuid} status={cand.status}")
        digest = hashlib.sha256(cand.content.encode()).hexdigest()
        if expected_hash and digest != expected_hash:
            raise TransportError(TransportErrorKind.CONTENT,
                                 f"candidate {uuid} hash mismatch")
        return cand.content


def _classify(exc: Exception) -> TransportErrorKind:
    if isinstance(exc, (FloodWaitError, SlowModeWaitError)):
        return TransportErrorKind.FLOOD_WAIT
    if isinstance(exc, (ChatWriteForbiddenError, UserBannedInChannelError,
                        ChannelPrivateError)):
        return TransportErrorKind.PERMISSION
    if isinstance(exc, (AuthKeyUnregisteredError, SessionRevokedError,
                        UnauthorizedError)):
        return TransportErrorKind.AUTH
    if isinstance(exc, (MessageEmptyError, PeerIdInvalidError, ValueError)):
        return TransportErrorKind.CONTENT
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return TransportErrorKind.RESULT_UNKNOWN
    return TransportErrorKind.TRANSIENT


class TelethonTransport(SendTransport):
    """Per-account live transport. Chat ids use Telethon's marked form
    (-100...); rules and this layer share that convention."""

    def __init__(self, client: TelegramClient, account_id: str,
                 registry: LiveRegistry, resolver: PayloadResolver):
        self.client = client
        self.account_id = account_id
        self.registry = registry
        self.resolver = resolver
        self._self_id: int | None = None

    async def _entity(self, target_id: int):
        # Telegram rejects PeerUser(self) in send/edit/delete — Saved
        # Messages must go through PeerSelf ('me').
        if self._self_id is None:
            self._self_id = (await self.client.get_me()).id
        return 'me' if target_id == self._self_id else target_id

    async def _call(self, fn: Callable[[], Awaitable]):
        try:
            return await fn()
        except TransportError:
            raise
        except (FloodWaitError, SlowModeWaitError) as exc:
            until = time.time() + float(exc.seconds)
            self.registry.mark_flood_wait(self.account_id, until)
            raise TransportError(TransportErrorKind.FLOOD_WAIT,
                                 str(exc), flood_wait_until=until)
        except Exception as exc:  # noqa: BLE001 — unknown RPC/IO errors all classify into the §8.3 taxonomy
            kind = _classify(exc)
            if kind is TransportErrorKind.AUTH:
                self.registry.mark_auth_dead(self.account_id)
            raise TransportError(kind, str(exc)[:300])

    async def _resolve_text(self, plan: DeliveryPlan) -> str | None:
        if plan.payload_ref and plan.payload_ref.startswith("candidate:"):
            return await self.resolver.candidate_text(
                plan.payload_ref.removeprefix("candidate:"), plan.payload_hash)
        return None

    async def send(self, plan: DeliveryPlan) -> list[int]:
        text = await self._resolve_text(plan)
        if text is not None:
            entity = await self._entity(plan.target_chat_id)
            msg = await self._call(lambda: self.client.send_message(
                entity, text,
                reply_to=plan.reply_to_target_message_id))
            return [msg.id]
        if plan.mode is CloneMode.FORWARD:
            msgs = await self._call(lambda: self.client.forward_messages(
                plan.target_chat_id, [plan.source_message_id],
                from_peer=plan.source_chat_id))
            return [m.id for m in msgs] if isinstance(msgs, list) else [msgs.id]
        # copy mode: re-send the source message's own content
        src = await self._call(lambda: self.client.get_messages(
            plan.source_chat_id, ids=plan.source_message_id))
        if src is None:
            raise TransportError(TransportErrorKind.CONTENT,
                                 "source message missing")
        entity = await self._entity(plan.target_chat_id)
        msg = await self._call(lambda: self.client.send_message(
            entity, getattr(src, "text", None) or "",
            file=getattr(src, "media", None),
            reply_to=plan.reply_to_target_message_id))
        return [msg.id]

    async def edit(self, plan: DeliveryPlan, target_message_id: int) -> None:
        src = await self._call(lambda: self.client.get_messages(
            plan.source_chat_id, ids=plan.source_message_id))
        if src is None:
            raise TransportError(TransportErrorKind.CONTENT,
                                 "source message missing for edit")
        entity = await self._entity(plan.target_chat_id)
        await self._call(lambda: self.client.edit_message(
            entity, target_message_id,
            getattr(src, "text", None) or "", file=getattr(src, "media", None)))

    async def delete(self, plan: DeliveryPlan,
                     target_message_ids: list[int]) -> None:
        entity = await self._entity(plan.target_chat_id)
        await self._call(lambda: self.client.delete_messages(
            entity, target_message_ids))


class TransportRouter(SendTransport):
    """One SendTransport for the shared executor; routes each plan to the
    per-account TelethonTransport. Unknown account = auth_dead upstream."""

    def __init__(self) -> None:
        self._routes: dict[str, TelethonTransport] = {}

    def add(self, account_id: str, transport: TelethonTransport) -> None:
        self._routes[account_id] = transport

    def drop(self, account_id: str) -> None:
        self._routes.pop(account_id, None)

    def _for(self, plan: DeliveryPlan) -> TelethonTransport:
        t = self._routes.get(plan.account_id)
        if t is None:
            raise TransportError(TransportErrorKind.AUTH,
                                 f"no live session for {plan.account_id}")
        return t

    async def send(self, plan: DeliveryPlan) -> list[int]:
        return await self._for(plan).send(plan)

    async def edit(self, plan: DeliveryPlan, target_message_id: int) -> None:
        await self._for(plan).edit(plan, target_message_id)

    async def delete(self, plan: DeliveryPlan,
                     target_message_ids: list[int]) -> None:
        await self._for(plan).delete(plan, target_message_ids)


def _chat_class(chat) -> ChatClass:
    if isinstance(chat, tl.Channel):
        return ChatClass.BROADCAST
    if isinstance(chat, tl.Chat):
        return ChatClass.SMALL_GROUP
    return ChatClass.PRIVATE


def _content_hash(message) -> str:
    h = hashlib.sha256()
    h.update((getattr(message, "message", "") or "").encode())
    if getattr(message, "entities", None):
        for e in message.entities:
            h.update(str(type(e).__name__).encode())
            h.update(str(getattr(e, "offset", "")).encode())
            h.update(str(getattr(e, "length", "")).encode())
    return h.hexdigest()


@dataclass(frozen=True)
class AccountSession:
    """A connected Telethon client built from control-plane session bytes.
    The sqlite file lives in a 0600 temp file wiped on close (§5.1)."""

    client: TelegramClient
    session_path: str

    @classmethod
    async def connect(cls, bundle: SessionBundle) -> AccountSession:
        fd, path = tempfile.mkstemp(prefix="tgsess_", suffix=".session")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(bundle.session_bytes)
            os.chmod(path, 0o600)
            client = TelegramClient(
                SQLiteSession(path), bundle.api_id, bundle.api_hash,
                device_model=bundle.device_model or "tg-platform",
                app_version=bundle.app_version or "",
            )
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                raise TransportError(TransportErrorKind.AUTH,
                                     "session not authorized")
            return cls(client=client, session_path=path)
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise

    async def close(self) -> None:
        try:
            await self.client.disconnect()
        finally:
            try:
                os.unlink(self.session_path)
            except OSError:
                pass


def make_ingest_handler(session_factory, account_id: str, tenant_id: str,
                        project_id: str, *, control=None, api_row_id: int | None = None):
    """Telethon event handler -> EventInbox.ingest (§6.4 boundary 1).

    control/api_row_id set → also reports new text messages to the control
    plane's AI trigger endpoint (fire-and-forget; failures never break ingest).
    """
    normalizer = EventNormalizer()

    async def on_update(event) -> None:
        try:
            for raw in _to_raws(event):
                src_event = normalizer.normalize(raw, account_id)
                async with session_factory() as s:
                    await EventInboxRepository(s).ingest(
                        src_event, tenant_id=tenant_id, project_id=project_id)
                if control is not None and api_row_id is not None and raw.kind is EventKind.CREATE:
                    await _report_ai_event(event, raw, control, api_row_id)
        except Exception:
            log.exception("ingest failed account=%s", account_id)

    return on_update


async def _report_ai_event(event, raw, control, api_row_id: int) -> None:
    """Best-effort group-message report for AI 炒群 (worker -> control plane)."""
    msg = getattr(event, "message", None)
    text = ((getattr(msg, "message", None) or "")).strip()
    if not text:
        return
    sender = getattr(msg, "sender", None)
    name = (
        getattr(sender, "username", None)
        or getattr(sender, "first_name", None)
        or str(raw.sender_id or "User")
    )
    try:
        await control.notify_ai_event({
            "api_row_id": api_row_id, "chat_id": raw.chat_id,
            "message_id": raw.message_id, "text": text[:2000],
            "sender_id": raw.sender_id, "sender_name": name,
            "topic_id": raw.topic_id,
        })
    except Exception:
        log.warning("ai event notify failed", exc_info=True)


def _sender_id(msg) -> int | None:
    """Telethon sender_id (None for service messages; channel id for anonymous
    admin posts — which therefore never match a user-id whitelist)."""
    sid = getattr(msg, "sender_id", None)
    if sid is not None:
        return sid
    from_id = getattr(msg, "from_id", None)
    return utils.get_peer_id(from_id) if from_id is not None else None


_MEDIA_ATTRS: tuple[tuple[str, str], ...] = (
    ("sticker", "sticker"),
    ("photo", "photo"),
    ("video", "video"),
    ("gif", "gif"),
    ("voice", "voice"),
    ("audio", "audio"),
    ("document", "document"),
    ("poll", "poll"),
    ("contact", "contact"),
    ("geo", "location"),
    ("venue", "location"),
)


def _media_kind(msg) -> str:
    """Classify a message into a coarse media bucket for target filtering.
    Order matters: sticker/gif are documents too, so they are tested first."""
    for attr, kind in _MEDIA_ATTRS:
        if getattr(msg, attr, None) is not None:
            return kind
    return "text"


def _to_raws(event) -> list[RawUpdate]:
    """Adapt one Telethon event into zero-or-more RawUpdates. MessageDeleted
    carries a whole deleted_ids list — each id is its own inbox row."""
    msg = getattr(event, "message", None)
    if isinstance(event, (events.NewMessage.Event, events.MessageEdited.Event)):
        if msg is None:
            return []
        chat = event.chat
        chat_class = _chat_class(chat) if chat is not None else ChatClass.PRIVATE
        chat_id = utils.get_peer_id(msg.peer_id) if msg.peer_id else event.chat_id
        reply_to = getattr(msg, "reply_to", None)
        kind = (EventKind.EDIT
                if isinstance(event, events.MessageEdited.Event)
                else EventKind.CREATE)
        return [RawUpdate(
            kind=kind, chat_id=chat_id, message_id=msg.id,
            chat_class=chat_class,
            edit_date_ts=int(msg.edit_date.timestamp())
            if getattr(msg, "edit_date", None) else None,
            content_hash=_content_hash(msg),
            grouped_id=getattr(msg, "grouped_id", None),
            reply_to_message_id=getattr(reply_to, "reply_to_msg_id", None),
            topic_id=getattr(reply_to, "reply_to_top_id", None)
            if reply_to else None,
            protected=bool(getattr(msg, "noforwards", False)),
            sender_id=_sender_id(msg),
            media_kind=_media_kind(msg),
        )]
    if isinstance(event, events.MessageDeleted.Event):
        chat_id = event.chat_id or 0
        return [
            RawUpdate(kind=EventKind.DELETE, chat_id=chat_id,
                      message_id=mid, chat_class=ChatClass.BROADCAST)
            for mid in (event.deleted_ids or [])
        ]
    return []


def register_live_events(session: AccountSession, handler) -> None:
    session.client.add_event_handler(handler, events.NewMessage)
    session.client.add_event_handler(handler, events.MessageEdited)
    session.client.add_event_handler(handler, events.MessageDeleted)

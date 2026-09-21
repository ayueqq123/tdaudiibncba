"""EventNormalizer: raw updates -> SourceEvent (§4.2 item 2).

Telethon event objects are adapted into `RawUpdate` at the worker boundary so
normalization stays pure and testable. Dedup keys and revisions are produced
here; persistence/dedup enforcement lives in storage's event_inbox.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from runtime.planner.model import EventKind, SourceEvent


class ChatClass(enum.Enum):
    BROADCAST = "broadcast"      # channel / supergroup: canonical peer scope
    SMALL_GROUP = "small_group"  # basic group: message ids are per-account view
    PRIVATE = "private"          # out of scope (§1.1), but classified explicitly


@dataclass(frozen=True)
class RawUpdate:
    """Telethon event adapted to plain data at the worker boundary."""

    kind: EventKind
    chat_id: int
    message_id: int
    chat_class: ChatClass
    edit_date_ts: int | None = None       # platform edit timestamp, for revision
    content_hash: str | None = None      # text+entities fingerprint of this revision
    grouped_id: int | None = None
    reply_to_message_id: int | None = None
    topic_id: int | None = None
    protected: bool = False              # noforwards / content protection flag
    payload_ref: str | None = None


def source_scope_for(chat_class: ChatClass, chat_id: int, account_id: str) -> str:
    """§6.2: scope namespaces message ids. Broadcast peers are canonical;
    small groups embed the receiving account so views never merge."""
    if chat_class is ChatClass.BROADCAST:
        return f"peer:{chat_id}"
    return f"peer:{chat_id}:acct:{account_id}"


def event_revision(kind: EventKind, raw: RawUpdate) -> int:
    """create = 1; edit = platform edit ts or content fingerprint; delete = high."""
    if kind is EventKind.CREATE:
        return 1
    if kind is EventKind.EDIT:
        if raw.edit_date_ts is not None:
            return int(raw.edit_date_ts)
        if raw.content_hash:
            return abs(hash(raw.content_hash)) % (2**31)
        return 2
    return 2**31 - 1  # tombstone dominates all revisions


def dedup_key(event: SourceEvent) -> str:
    return (
        f"{event.source_scope}:{event.source_chat_id}:{event.source_message_id}:"
        f"{event.kind.value}:{event.revision}"
    )


class EventNormalizer:
    def normalize(self, raw: RawUpdate, account_id: str) -> SourceEvent:
        return SourceEvent(
            kind=raw.kind,
            source_scope=source_scope_for(raw.chat_class, raw.chat_id, account_id),
            source_chat_id=raw.chat_id,
            source_message_id=raw.message_id,
            revision=event_revision(raw.kind, raw),
            account_id=account_id,
            grouped_id=raw.grouped_id,
            payload_ref=raw.payload_ref,
            payload_hash=raw.content_hash,
            reply_to_source_id=raw.reply_to_message_id,
            topic_id=raw.topic_id,
            protected=raw.protected,
        )

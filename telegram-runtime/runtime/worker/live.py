"""Live Telethon side of the worker: session connect, SendTransport impl,
and update->event_inbox ingress (§4.2/§4.3).

Isolation model: one TelethonTransport + one TelegramClient per account,
keyed by account uuid. Every send path funnels through the executor's
SendPolicy gate upstream; this layer only maps Telegram outcomes into the
§8.3 error taxonomy and feeds the LiveRegistry the policy gate reads.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import re
import tempfile
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import (
    DBAPIError,
    OperationalError,
    TimeoutError as SQLAlchemyTimeoutError,
)
from telethon import TelegramClient, events, functions, utils
from telethon.errors import (
    AuthKeyUnregisteredError,
    ChannelInvalidError,
    ChannelPrivateError,
    ChatWriteForbiddenError,
    FloodWaitError,
    FrozenMethodInvalidError,
    MessageEmptyError,
    PeerIdInvalidError,
    SessionRevokedError,
    SlowModeWaitError,
    UnauthorizedError,
    UserBannedInChannelError,
    UserNotParticipantError,
)
from telethon.sessions import SQLiteSession
from telethon.tl import types as tl

from runtime.delivery import watermark
from runtime.delivery.executor import SendTransport, TransportError, TransportErrorKind
from runtime.delivery.policy import LiveAccount, SendState
from runtime.ingest.normalizer import ChatClass, EventNormalizer, RawUpdate
from runtime.planner.model import CloneMode, DeliveryPlan, EventKind
from runtime.storage.repos import EventInboxRepository
from runtime.worker.control_client import ControlClient, SessionBundle

log = logging.getLogger(__name__)

_RPC_TIMEOUT_S = 120.0
_EDIT_AS_CREATE_WINDOW_S = 900
_SENDER_BOT_CACHE_MAX = 50_000
_SENDER_BOT: OrderedDict[int, bool] = OrderedDict()


def _record_sender_bot(sender_id: int | None, sender) -> bool:
    is_bot = bool(getattr(sender, "bot", False)) or (
        (getattr(sender, "username", None) or "").lower().endswith("bot")
    )
    if type(sender_id) is int and sender_id > 0:
        _SENDER_BOT[sender_id] = is_bot
        _SENDER_BOT.move_to_end(sender_id)
        if len(_SENDER_BOT) > _SENDER_BOT_CACHE_MAX:
            _SENDER_BOT.popitem(last=False)
    return is_bot


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

    async def clone_transform(self, rule_id: str, text: str) -> dict:
        """发送前过控制面变形闸;网络/服务错按 TRANSIENT 重试。"""
        try:
            return await self._control.clone_transform(rule_id, text)
        except TransportError:
            raise
        except Exception as exc:  # noqa: BLE001 — 控制面调用失败一律可重试
            raise TransportError(TransportErrorKind.TRANSIENT,
                                 f"clone_transform: {exc!r}"[:300])


def _classify(exc: Exception) -> TransportErrorKind:
    if isinstance(exc, (FloodWaitError, SlowModeWaitError)):
        return TransportErrorKind.FLOOD_WAIT
    if isinstance(exc, (ChatWriteForbiddenError, UserBannedInChannelError,
                        ChannelPrivateError)):
        return TransportErrorKind.PERMISSION
    if isinstance(exc, (AuthKeyUnregisteredError, SessionRevokedError,
                        UnauthorizedError, FrozenMethodInvalidError)):
        return TransportErrorKind.AUTH
    if isinstance(exc, (MessageEmptyError, PeerIdInvalidError, ValueError)):
        return TransportErrorKind.CONTENT
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return TransportErrorKind.RESULT_UNKNOWN
    return TransportErrorKind.TRANSIENT


def _sniff_media_bytes(data: bytes) -> tuple[str | None, str | None]:
    """按字节魔数识别下载结果的格式,返回 (ext, mime)。

    文档缺文件名且 mime 映射不出扩展名(或 octet-stream)时兜底——保住图片
    走 photo 发送,而不是落地成 media.bin 文件。"""
    if data[:3] == b'\xff\xd8\xff':
        return '.jpg', 'image/jpeg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return '.png', 'image/png'
    if data[:6] in (b'GIF87a', b'GIF89a'):
        return '.gif', 'image/gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp', 'image/webp'
    if data[4:8] == b'ftyp':
        return '.mp4', 'video/mp4'
    if data[:4] == b'OggS':
        return '.ogg', 'audio/ogg'
    if data[:2] == b'\x1f\x8b':
        return '.tgs', 'application/x-tgsticker'
    if data[:4] == b'PK\x03\x04':
        return '.zip', 'application/zip'
    if data.startswith(b'BEGIN:VCARD'):
        return '.vcf', 'text/vcard'
    return None, None


class TelethonTransport(SendTransport):
    """Per-account live transport. Chat ids use Telethon's marked form
    (-100...); rules and this layer share that convention."""

    def __init__(self, client: TelegramClient, account_id: str,
                 registry: LiveRegistry, resolver: PayloadResolver,
                 status_cb: Callable[[str, str], Awaitable[None]] | None = None,
                 session_factory=None):
        self.client = client
        self.account_id = account_id
        self.registry = registry
        self.resolver = resolver
        self.status_cb = status_cb
        self.session_factory = session_factory
        self._self_id: int | None = None
        self._reported: set[str] = set()

    async def _report_dead(self, status: str, exc: Exception) -> None:
        """死号/禁言/冻结透出到控制面账号状态;同状态只报一次。"""
        if self.status_cb is None or status in self._reported:
            return
        self._reported.add(status)
        try:
            await self.status_cb(status, str(exc)[:300])
        except Exception:  # noqa: BLE001 — 上报失败不影响发送判定
            log.warning("status report failed account=%s", self.account_id)

    async def _entity(self, target_id: int):
        # Telegram rejects PeerUser(self) in send/edit/delete — Saved
        # Messages must go through PeerSelf ('me').
        if self._self_id is None:
            self._self_id = (await self._call(self.client.get_me)).id
        return 'me' if target_id == self._self_id else target_id

    async def _call(self, fn: Callable[[], Awaitable]):
        try:
            # 长连 MTProto 连接可能静默断开:已断连的 send_message 会立即抛
            # ConnectionError。发请求前先确认连接存活,断了就重建——这不是
            # "不确定结果重发",此时请求尚未离手。
            if not self.client.is_connected():
                await self.client.connect()
            # 请求级超时:半死连接上的 RPC 会无声挂起,job 永远停在 sending。
            # 超时记 RESULT_UNKNOWN——请求可能已离手,结果不确定不盲重发。
            async with asyncio.timeout(_RPC_TIMEOUT_S):
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
                status = ("frozen" if isinstance(exc, FrozenMethodInvalidError)
                          else "auth_dead")
                await self._report_dead(status, exc)
            elif kind is TransportErrorKind.PERMISSION:
                await self._report_dead("banned", exc)
            raise TransportError(kind, str(exc)[:300])

    async def _resolve_text(self, plan: DeliveryPlan) -> str | None:
        if plan.payload_ref and plan.payload_ref.startswith("candidate:"):
            return await self.resolver.candidate_text(
                plan.payload_ref.removeprefix("candidate:"), plan.payload_hash)
        return None

    async def _fetch_source(self, plan: DeliveryPlan,
                            fetcher: TelethonTransport):
        """源消息统一经监听号 fetcher 回取——发送号不需要在源群。
        fetcher 的 _call 把错误记到 fetcher 自己的 registry。"""
        src = await fetcher._call(lambda: fetcher.client.get_messages(
            plan.source_chat_id, ids=plan.source_message_id))
        if src is None:
            raise TransportError(TransportErrorKind.CONTENT,
                                 "source message missing")
        return src

    async def resolve_album(
        self, plan: DeliveryPlan, *,
        fetcher: TelethonTransport | None = None,
    ) -> list[int]:
        fetcher = fetcher or self
        if plan.grouped_id is None:
            return []
        mid = plan.source_message_id
        try:
            messages = await fetcher._call(lambda: fetcher.client.get_messages(
                plan.source_chat_id, ids=list(range(mid - 9, mid + 10))))
        except Exception as exc:
            raise TransportError(TransportErrorKind.TRANSIENT,
                                 str(exc)[:300]) from exc
        if messages is None:
            return []
        if not isinstance(messages, (list, tuple)):
            messages = [messages]
        return sorted({
            message.id for message in messages
            if message is not None
            and getattr(message, "grouped_id", None) == plan.grouped_id
        })

    async def _media_file(self, src, fetcher: TelethonTransport,
                          wm_mode: str = "off", wm_mask: str | None = None):
        """同号直传 TL media(快路径);跨账号下载 bytes 由发送号重传
        (file_reference 与账号绑定,不能直接把别的号抓到的 media 发出去)。
        wm_mode != off 时强制下载重传——去水印必须拿到原始字节做处理。
        返回 (file, attributes, mime_type):裸 bytes 会被当无名文件发,故带上
        原名/扩展名 + 原文档 mime_type + 原文档属性(视频时长宽高、语音时长等),
        否则源端是 octet-stream 的视频会落地成文件。"""
        media = getattr(src, "media", None)
        if media is None:
            return None, None, None
        if isinstance(media, tl.MessageMediaContact):
            # 名片:download_media 只能取到 vCard 文本,重发落地成
            # media.bin 文件;改用原生 InputMediaContact 保住名片形态。
            return tl.InputMediaContact(
                phone_number=media.phone_number,
                first_name=media.first_name,
                last_name=media.last_name,
                vcard=media.vcard,
            ), None, None
        if fetcher is self and wm_mode == "off":
            return media, None, None
        data = await fetcher._call(lambda: src.download_media(file=bytes))
        if data is None:
            return None, None, None
        doc = getattr(src, 'document', None)
        attrs = list(getattr(doc, 'attributes', None) or [])
        mime = getattr(doc, 'mime_type', None)
        f = getattr(src, 'file', None)
        name = getattr(f, 'name', None)
        if name is None:
            ext = getattr(f, 'ext', None)
            # 缺文件名且 mime 映射不出扩展名(或 octet-stream 兜底 .bin)时,
            # 用字节魔数嗅探真实格式——否则图片/贴纸等会落地成 media.bin 文件。
            if ext in (None, '.bin') or mime in (None, 'application/octet-stream'):
                sniff_ext, sniff_mime = _sniff_media_bytes(data)
                if sniff_ext is not None:
                    ext = sniff_ext
                if sniff_mime is not None and mime in (None, 'application/octet-stream'):
                    mime = sniff_mime
            name = f'media{ext}' if ext else 'media.bin'
        if wm_mode != "off":
            # 去水印:图片 inpaint / 视频 delogo;失败回退原 bytes
            data = await asyncio.to_thread(
                watermark.clean_bytes, data, name, wm_mode, wm_mask)
        buf = io.BytesIO(data)
        buf.name = name
        return buf, attrs, mime

    # clone_transform 前置闸:规则配置 60s 本地缓存 + 便宜判定本地完成,
    # 命中就不必走 control-api HTTP。正则与 backend ai_service._AD_SIGNALS 保持一致。
    _RULE_CFG_TTL_S = 60.0
    _RESULT_CACHE_TTL_S = 86400.0
    _RESULT_CACHE_MAX = 20000
    _RULE_CFG_STORE: dict[str, tuple[float, dict | None]] = {}
    _result_cache: dict[str, tuple[float, str]] = {}
    _AD_SIGNALS_LOCAL = tuple(re.compile(rx, re.I) for rx in (
        r't\.me/|telegram\.(me|dog)/',
        r'@[A-Za-z][A-Za-z0-9_]{3,}',
        r'https?://|bit\.ly|cutt\.ly|t\.co/|goo\.gl|is\.gd|tinyurl\.com',
        r'微信|wechat|qq号|qq[:：＝=]?\d{5,}|vx[:：＝=]|whatsapp|whats\s*app|飞机号|纸飞机|TG号|tg号|tele号|line[:：＝=]|蝙蝠|potato|土豆聊天|泡泡聊天',
        r'加我|私聊|私我|pm我|联系客服|接单|直推|扶持|团队收人|副业|兼职|日结|底薪|躺赚|免费领|进群|加群|进频道|点链接|扫码|福利|优惠|代理|招商|高返|返佣|首充|包赚|稳赚',
        r'盘口|菠菜|棋牌|百家乐|上分|下分|赔率|六合彩|亚博|开元|开云|ag真人|电子游艺|老虎机|彩票|投注|下注|押注|洗码|返水|打鱼',
        r'usdt|泰达币|u币|换汇|跑分|套现|代付|代充|承兑|搬砖|灰产|洗钱|代收',
        r'上门服务|约炮|黄播|裸聊|援交|办证|办签证|假证|护照办理|驾照包过',
        r'币安|binance|欧易|okx|火币|imtoken|bitget|gate\.io|抹茶',
    ))

    @staticmethod
    def _has_ad_signal(text: str) -> bool:
        return any(rx.search(text) for rx in TelethonTransport._AD_SIGNALS_LOCAL)

    async def _rule_cfg(self, rule_id: str) -> dict | None:
        now = time.monotonic()
        ent = TelethonTransport._RULE_CFG_STORE.get(rule_id)
        if ent and now - ent[0] < TelethonTransport._RULE_CFG_TTL_S:
            return ent[1]
        cfg = None
        if self.session_factory is not None:
            try:
                from sqlalchemy import text as _sql  # noqa: PLC0415
                async with self.session_factory() as s:
                    row = (await s.execute(_sql(
                        'select ad_keywords, ad_block, ai_rewrite, ai_prompt'
                        ' from tg_clone_rule where id = :rid and deleted = 0'),
                        {'rid': int(rule_id)})).mappings().first()
                if row is not None:
                    cfg = dict(row)
            except Exception as exc:  # noqa: BLE001 — 读不到就回落远端判定
                log.warning("rule cfg fetch failed rule=%s: %r", rule_id, exc)
        TelethonTransport._RULE_CFG_STORE[rule_id] = (now, cfg)
        return cfg

    async def _pre_gate(self, plan: DeliveryPlan, text: str) -> str | None:
        '''返回 None = 需要远端 AI 判定;否则本地结果(原文/缓存文案)。'''
        cfg = await self._rule_cfg(plan.rule_id)
        if cfg is None:
            return None
        low = text.lower()
        kws = [str(k).strip() for k in (cfg.get('ad_keywords') or []) if str(k).strip()]
        if any(k.lower() in low for k in kws):
            raise TransportError(TransportErrorKind.FILTERED, 'dropped:keyword')
        need_ai = (cfg.get('ad_block') or 'off') == 'ai' \
            or (cfg.get('ai_rewrite') or 'off') not in ('', 'off')
        if not need_ai:
            return text
        ad_only = (cfg.get('ad_block') or 'off') == 'ai' \
            and (cfg.get('ai_rewrite') or 'off') in ('', 'off')
        if ad_only and len(text.strip()) <= 10 and not self._has_ad_signal(text):
            return text
        ck = hashlib.sha256(
            f"{plan.rule_id}|{cfg.get('ai_rewrite')}|{cfg.get('ad_block')}|"
            f"{cfg.get('ai_prompt') or ''}|{text}".encode()).hexdigest()[:32]
        ent = TelethonTransport._result_cache.get(ck)
        if ent and time.monotonic() - ent[0] < TelethonTransport._RESULT_CACHE_TTL_S:
            return ent[1]
        return None

    def _cache_result(self, plan: DeliveryPlan, text: str, out: str) -> None:
        cfg = TelethonTransport._RULE_CFG_STORE.get(plan.rule_id)
        fields = cfg[1] if cfg else {}
        ck = hashlib.sha256(
            f"{plan.rule_id}|{fields.get('ai_rewrite')}|{fields.get('ad_block')}|"
            f"{fields.get('ai_prompt') or ''}|{text}".encode()).hexdigest()[:32]
        cache = TelethonTransport._result_cache
        if len(cache) >= TelethonTransport._RESULT_CACHE_MAX:
            cache.clear()  # 简单重建:TTL 内重填,省逐条过期维护
        cache[ck] = (time.monotonic(), out)

    async def _transform(self, plan: DeliveryPlan, text: str) -> str:
        if not plan.transform or not text.strip():
            return text
        pre = await self._pre_gate(plan, text)
        if pre is not None:
            log.info("clone_transform rule=%s src_msg=%s action=send reason='local' "
                     "changed=%s len %d->%d", plan.rule_id,
                     plan.source_message_id, pre != text, len(text), len(pre))
            return pre
        r = await self.resolver.clone_transform(plan.rule_id, text)
        if r.get("action") == "drop":
            raise TransportError(TransportErrorKind.FILTERED,
                                 f"dropped:{r.get('reason') or 'filtered'}")
        out = str(r.get("text") or text)
        log.info("clone_transform rule=%s src_msg=%s action=send reason=%r "
                 "changed=%s len %d->%d", plan.rule_id,
                 plan.source_message_id, r.get("reason") or "",
                 out != text, len(text), len(out))
        if r.get("reason") in ("", "cache"):
            self._cache_result(plan, text, out)
        return out

    async def send(self, plan: DeliveryPlan,
                   *, fetcher: TelethonTransport | None = None) -> list[int]:
        fetcher = fetcher or self
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
        # copy mode: re-send the source message's own content(经监听号回取)
        src = await self._fetch_source(plan, fetcher)
        entity = await self._entity(plan.target_chat_id)
        # caption 也过 AI 变形闸(广告/链接大多在 caption 里);media 本体透传,
        # 去水印在 _media_file 内按规则处理
        text = await self._transform(plan, getattr(src, "text", None) or "")
        file, attrs, mime = await self._media_file(
            src, fetcher, plan.watermark_mode, plan.watermark_mask)
        if file is None:
            msg = await self._call(lambda: self.client.send_message(
                entity, text,
                reply_to=plan.reply_to_target_message_id))
        else:
            msg = await self._call(lambda: self.client.send_file(
                entity, file, caption=text, attributes=attrs, mime_type=mime,
                reply_to=plan.reply_to_target_message_id))
        return [msg.id]

    async def send_album(self, plans: list[DeliveryPlan],
                         *, fetcher: TelethonTransport | None = None) -> list[int]:
        """同一 grouped_id 的多个 plan 合并成一条相册消息发送(一次 send_file
        传文件列表)。caption 取首个非空成员文案,整组只过一次变形闸;无媒体的
        成员(纯文本/candidate)退回逐条发送。返回按 plans 顺序的目标消息 id
        (无媒体的成员位置填其单独发送的 id)。"""

        async def send_one(plan: DeliveryPlan) -> int:
            return (await self.send(plan, fetcher=fetcher))[0]

        fetcher = fetcher or self
        files: list = []
        captions: list[str] = []
        media_plans: list[DeliveryPlan] = []
        solo_plans: list[DeliveryPlan] = []
        fwd_plans: list[DeliveryPlan] = []
        for plan in plans:
            # candidate 文本(审批/快照存的外部队列)无源媒体,单独走
            if await self._resolve_text(plan) is not None:
                solo_plans.append(plan)
                continue
            if plan.mode is CloneMode.FORWARD:
                fwd_plans.append(plan)
                continue
            src = await self._fetch_source(plan, fetcher)
            file, _attrs, _mime = await self._media_file(
                src, fetcher, plan.watermark_mode, plan.watermark_mask)
            if file is None:
                solo_plans.append(plan)
                continue
            files.append(file)
            media_plans.append(plan)
            captions.append(getattr(src, "text", None) or "")

        out: dict[int, int] = {}
        if files:
            entity = await self._entity(media_plans[0].target_chat_id)
            # 每个成员自己的 caption 逐个过变形闸;任一被判广告 → 整组丢弃
            captions = [await self._transform(media_plans[i], c)
                        if c.strip() else c
                        for i, c in enumerate(captions)]
            msgs = await self._call(lambda: self.client.send_file(
                entity, files, caption=captions,
                reply_to=media_plans[0].reply_to_target_message_id))
            msg_list = msgs if isinstance(msgs, list) else [msgs]
            for plan, m in zip(media_plans, msg_list):
                out[plan.source_message_id] = m.id
            # 返回少于成员:剩余成员退回逐条发送,不丢内容
            for plan in media_plans[len(msg_list):]:
                out[plan.source_message_id] = await send_one(plan)
        if fwd_plans:
            # forward 模式:整组转发,TG 还原成相册
            msgs = await self._call(lambda: self.client.forward_messages(
                fwd_plans[0].target_chat_id,
                [p.source_message_id for p in fwd_plans],
                from_peer=fwd_plans[0].source_chat_id))
            msg_list = msgs if isinstance(msgs, list) else [msgs]
            for plan, m in zip(fwd_plans, msg_list):
                out[plan.source_message_id] = m.id
            for plan in fwd_plans[len(msg_list):]:
                out[plan.source_message_id] = await send_one(plan)
        for plan in solo_plans:
            out[plan.source_message_id] = await send_one(plan)
        return [out[p.source_message_id] for p in plans]

    async def edit(self, plan: DeliveryPlan, target_message_id: int,
                   *, fetcher: TelethonTransport | None = None) -> None:
        fetcher = fetcher or self
        src = await self._fetch_source(plan, fetcher)
        entity = await self._entity(plan.target_chat_id)
        text = await self._transform(plan, getattr(src, "text", None) or "")
        file, attrs, mime = await self._media_file(
            src, fetcher, plan.watermark_mode, plan.watermark_mask)
        # edit_message 不接 attributes;用原文件名已能保住媒体类型
        await self._call(lambda: self.client.edit_message(
            entity, target_message_id, text, file=file))

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

    def _fetcher_for(self, plan: DeliveryPlan) -> TelethonTransport | None:
        return self._routes.get(plan.fetch_account_id or plan.account_id)

    async def send(self, plan: DeliveryPlan) -> list[int]:
        return await self._for(plan).send(plan, fetcher=self._fetcher_for(plan))

    async def resolve_album(self, plan: DeliveryPlan) -> list[int]:
        return await self._for(plan).resolve_album(
            plan, fetcher=self._fetcher_for(plan))

    async def send_album(self, plans: list[DeliveryPlan]) -> list[int]:
        return await self._for(plans[0]).send_album(
            plans, fetcher=self._fetcher_for(plans[0]))

    async def edit(self, plan: DeliveryPlan, target_message_id: int) -> None:
        await self._for(plan).edit(plan, target_message_id,
                                   fetcher=self._fetcher_for(plan))

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
            if isinstance(event, (events.NewMessage.Event, events.MessageEdited.Event)):
                message = getattr(event, "message", None)
                if message is not None:
                    await _resolve_sender_bot(message)
            for raw in _to_raws(event):
                src_event = normalizer.normalize(raw, account_id)
                for attempt in range(3):
                    try:
                        async with session_factory() as s:
                            await EventInboxRepository(s).ingest(
                                src_event, tenant_id=tenant_id,
                                project_id=project_id)
                        break
                    except (
                        SQLAlchemyTimeoutError, OperationalError, DBAPIError,
                    ):
                        if attempt == 2:
                            raise
                        await asyncio.sleep(0.5 if attempt == 0 else 1.5)
                if (
                    control is not None
                    and api_row_id is not None
                    and isinstance(event, events.NewMessage.Event)
                    and raw.kind is EventKind.CREATE
                ):
                    _schedule_ai_notify(event, raw, control, api_row_id)
        except Exception:
            log.exception("ingest failed account=%s", account_id)

    return on_update


def _display_name(sender) -> str | None:
    """Telegram nickname as shown in the group; falls back to @username."""
    if sender is None:
        return None
    nick = " ".join(
        p for p in (getattr(sender, "first_name", None), getattr(sender, "last_name", None)) if p
    ).strip() or (getattr(sender, "title", None) or "").strip()
    return nick or getattr(sender, "username", None)




_AI_NOTIFY_MAX_INFLIGHT = 64
_ai_notify_inflight: set[asyncio.Task] = set()
_ai_notify_stats = {"dropped": 0, "failed": 0}
_ai_notify_last_warn = 0.0


def _ai_notify_warn(msg: str) -> None:
    """60s 节流:控制面故障时失败/丢弃风暴不刷屏。"""
    global _ai_notify_last_warn
    now = time.monotonic()
    if now - _ai_notify_last_warn >= 60:
        _ai_notify_last_warn = now
        log.warning("ai event notify degraded: %s", msg)


def _schedule_ai_notify(event, raw, control, api_row_id: int) -> None:
    """AI 事件上报改后台任务 + 有界在飞:控制面慢/挂不再阻塞 ingest;
    在飞数满直接丢弃(best-effort),失败计数周期性进日志。"""
    if len(_ai_notify_inflight) >= _AI_NOTIFY_MAX_INFLIGHT:
        _ai_notify_stats["dropped"] += 1
        _ai_notify_warn(
            f"inflight full dropped={_ai_notify_stats['dropped']}")
        return
    task = asyncio.ensure_future(
        _report_ai_event(event, raw, control, api_row_id))
    _ai_notify_inflight.add(task)
    task.add_done_callback(_ai_notify_inflight.discard)


async def _report_ai_event(event, raw, control, api_row_id: int) -> None:
    """Best-effort group-message report for AI 炒群 (worker -> control plane)."""
    msg = getattr(event, "message", None)
    text = ((getattr(msg, "message", None) or "")).strip()
    if not text:
        return
    sender = getattr(msg, "sender", None)
    name = _display_name(sender) or str(raw.sender_id or "User")
    try:
        await control.notify_ai_event({
            "api_row_id": api_row_id, "chat_id": raw.chat_id,
            "message_id": raw.message_id, "text": text[:2000],
            "sender_id": raw.sender_id, "sender_name": name,
            "topic_id": raw.topic_id,
            "reply_to_message_id": raw.reply_to_message_id,
            "chat_class": raw.chat_class.value,
            "sender_is_bot": bool(raw.sender_is_bot),
        })
    except Exception as exc:
        _ai_notify_stats["failed"] += 1
        _ai_notify_warn(
            f"{exc!r} failed={_ai_notify_stats['failed']} "
            f"dropped={_ai_notify_stats['dropped']}")


def _sender_id(msg) -> int | None:
    """Telethon sender_id (None for service messages; channel id for anonymous
    admin posts — which therefore never match a user-id whitelist)."""
    sid = getattr(msg, "sender_id", None)
    if sid is not None:
        return sid
    from_id = getattr(msg, "from_id", None)
    return utils.get_peer_id(from_id) if from_id is not None else None


async def _resolve_sender_bot(msg) -> None:
    sender_id = None
    try:
        sender_id = _sender_id(msg)
        if type(sender_id) is not int or sender_id <= 0 or sender_id in _SENDER_BOT:
            return
        sender = getattr(msg, "sender", None)
        if sender is None:
            sender = await asyncio.wait_for(msg.get_sender(), timeout=5)
        if sender is None:
            log.debug("could not resolve sender bot status sender_id=%s: no sender",
                      sender_id)
            return
        _record_sender_bot(sender_id, sender)
    except Exception:
        log.debug("could not resolve sender bot status sender_id=%s",
                  sender_id, exc_info=True)


def _sender_is_bot(msg) -> bool:
    """True when the author is a bot account or sent via an inline bot."""
    if getattr(msg, "via_bot_id", None):
        return True
    sender_id = _sender_id(msg)
    sender = getattr(msg, "sender", None)
    if sender is not None:
        return _record_sender_bot(sender_id, sender)
    return _SENDER_BOT.get(sender_id, False)


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


def _topic_id(reply_to) -> int | None:
    """Forum topic of a message. reply_to_top_id alone is the reply-thread
    root in ordinary groups, not a topic."""
    if reply_to is None or not getattr(reply_to, "forum_topic", False):
        return None
    return (getattr(reply_to, "reply_to_top_id", None)
            or getattr(reply_to, "reply_to_msg_id", None))


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
        edit_date_ts = (
            int(msg.edit_date.timestamp())
            if getattr(msg, "edit_date", None) else None
        )
        common = dict(
            chat_id=chat_id, message_id=msg.id, chat_class=chat_class,
            content_hash=_content_hash(msg),
            grouped_id=getattr(msg, "grouped_id", None),
            reply_to_message_id=getattr(reply_to, "reply_to_msg_id", None),
            topic_id=_topic_id(reply_to),
            protected=bool(getattr(msg, "noforwards", False)),
            sender_id=_sender_id(msg),
            media_kind=_media_kind(msg),
            sender_is_bot=_sender_is_bot(msg),
        )
        if isinstance(event, events.MessageEdited.Event):
            message_date = getattr(msg, "date", None)
            if (
                message_date is not None
                and abs((datetime.now(UTC) - message_date).total_seconds())
                <= _EDIT_AS_CREATE_WINDOW_S
            ):
                return [
                    RawUpdate(kind=EventKind.CREATE, edit_date_ts=None, **common),
                    RawUpdate(kind=EventKind.EDIT, edit_date_ts=edit_date_ts, **common),
                ]
            return [RawUpdate(
                kind=EventKind.EDIT, edit_date_ts=edit_date_ts, **common,
            )]
        return [RawUpdate(
            kind=EventKind.CREATE, edit_date_ts=edit_date_ts, **common,
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


async def check_membership(client: TelegramClient, chat_id: int) -> str | None:
    """Return a lost-reason when the account is verifiably no longer in a
    supergroup/channel ("kicked" | "not_member"); None when still a member or
    undeterminable (basic groups, uncached peers, transient errors)."""
    if not str(chat_id).startswith("-100"):
        return None
    try:
        peer = await client.get_input_entity(chat_id)
    except (ValueError, TypeError):
        return None
    try:
        await client(functions.channels.GetParticipantRequest(peer, tl.InputUserSelf()))
    except (ChannelPrivateError, ChannelInvalidError):
        return "kicked"
    except UserNotParticipantError:
        return "not_member"
    except Exception:  # unknown ≠ lost; never flag on transient errors
        log.warning("membership check failed chat=%s", chat_id, exc_info=True)
    return None


def register_membership_watch(
    session: AccountSession,
    watched: Callable[[], set[int]],
    on_lost: Callable[[int, str], Awaitable[None]],
) -> None:
    """Kicked accounts only receive a bare UpdateChannel (no service message),
    so every UpdateChannel for a watched chat triggers a membership probe."""
    client = session.client

    async def on_raw(update) -> None:
        if not isinstance(update, tl.UpdateChannel):
            return
        chat_id = utils.get_peer_id(tl.PeerChannel(update.channel_id))
        if chat_id not in watched():
            return
        reason = await check_membership(client, chat_id)
        if reason:
            await on_lost(chat_id, reason)

    client.add_event_handler(on_raw, events.Raw)

import asyncio
import hashlib
import json
import random
import re

from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.task.celery import celery_app
from backend.app.tg.crud.crud_ai import (
    ai_binding_dao,
    ai_callback_dao,
    ai_conversation_dao,
    ai_group_dao,
    ai_private_reply_dao,
    ai_run_dao,
)
from backend.app.tg.crud.crud_approval import approval_dao, reply_candidate_dao
from backend.app.tg.crud.crud_telegram_account import telegram_account_dao
from backend.app.tg.metrics import tg_ai_callback_total, tg_ai_run_active, tg_ai_run_total
from backend.app.tg.model import TgReplyCandidate, TgTelegramAccount
from backend.app.tg.model.ai import TgAiBinding, TgAiCallback, TgAiConversation, TgAiGroup, TgAiRun, TgAiScript
from backend.app.tg.schema.ai import (
    AiGroupEventParam,
    AiTriggerParam,
    CreateAiBindingParam,
    CreateAiCallbackParam,
    CreateAiConversationParam,
    CreateAiRunParam,
    UpdateAiBindingParam,
)
from backend.app.tg.schema.approval import CreateApprovalParam, CreateReplyCandidateParam
from backend.app.tg.service.account_service import JOIN_ERR, join_chat_refs
from backend.app.tg.service.ai_engine import (
    langbot_engine_adapter,
    openai_complete,
    resolve_secret,
    verify_callback_signature,
)
from backend.app.tg.service.approval_service import ApprovalService
from backend.common.exception import errors
from backend.core.conf import settings
from backend.database.db import uuid4_str
from backend.database.redis import redis_client
from backend.utils.encrypt import ItsDCipher
from backend.utils.timezone import timezone

# 回调缺失判定窗口:LangBot 侧回调内存队列不可信(§9.5),到期标 incomplete
RUN_DEADLINE_SECONDS = 180
OPENAI_GENERATE_TASK = 'backend.app.task.tasks.tg.tasks.tg_ai_openai_generate'
SCRIPT_STEP_TASK = 'backend.app.task.tasks.tg.tasks.tg_ai_script_step'
MIN_DISPATCH_COUNTDOWN_S = 2.0
ACTIVE_RUN_STATUSES = ('pending', 'dispatched', 'running')
GROUP_EVENT_CLAIM_TTL_S = 86400
# 候选有效期:审批 SLA 之外的安全边界
CANDIDATE_TTL_HOURS = 24

DEFAULT_PERSONA = (
    '你是一个群聊里的普通成员,说话自然简短,像真人聊天。不要承认自己 AI,不要输出括号动作描述,不要长篇大论。'
)


def _provider_cipher() -> ItsDCipher:
    """模型 API key 加解密器:TOKEN_SECRET_KEY 派生 32 字节密钥。"""
    key = hashlib.sha256(settings.TOKEN_SECRET_KEY.encode()).digest()
    return ItsDCipher(key)


def _norm(s: str) -> str:
    return ''.join(ch for ch in s if ch.isalnum())


_PUNCT_TO_SPACE = str.maketrans(dict.fromkeys('，。、；：,;:', ' '))


def _strip_punct(s: str) -> str:
    """口语化:逗号句号类标点换成空格,连续空白收敛;情绪类标点(?!~…)保留"""
    return ' '.join(s.translate(_PUNCT_TO_SPACE).split())


class AiService:
    """AI 链路编排(§9.2):trigger → ai_run → LangBot → callback → candidate → approval。"""

    @staticmethod
    async def _current_epoch(db: AsyncSession, binding: TgAiBinding, obj: AiTriggerParam) -> int:
        """取该会话域最新的 context_epoch;新建会话从 0 起。"""
        convs = await ai_conversation_dao.get_all(db, tenant_id=binding.tenant_id, project_id=binding.project_id)
        return max(
            (
                c.context_epoch
                for c in convs
                if c.chat_id == obj.chat_id and c.topic_id == obj.topic_id and c.agent_key == obj.agent_key
            ),
            default=0,
        )

    @staticmethod
    async def trigger(*, db: AsyncSession, obj: AiTriggerParam, defer: bool = False) -> TgAiRun:
        """创建会话(若无)→组装内嵌上下文消息→建 run→提交 LangBot。

        defer=True(仅 openai 引擎):run 挂 pending,发言延迟+生成交给 Celery 任务,调用方立即返回。"""
        binding = await ai_binding_dao.get(db, obj.binding_id)
        if not binding or binding.status != 'active':
            raise errors.NotFoundError(msg='AI 绑定不存在或已停用')

        epoch = await AiService._current_epoch(db, binding, obj)
        conv = await ai_conversation_dao.get_by_scope(
            db,
            tenant_id=binding.tenant_id,
            project_id=binding.project_id,
            chat_id=obj.chat_id,
            topic_id=obj.topic_id,
            agent_key=obj.agent_key,
            context_epoch=epoch,
        )
        if conv is None:
            conv = await ai_conversation_dao.create(
                db,
                CreateAiConversationParam(
                    tenant_id=binding.tenant_id,
                    project_id=binding.project_id,
                    account_id=binding.account_id,
                    binding_id=binding.id,
                    chat_id=obj.chat_id,
                    topic_id=obj.topic_id,
                    agent_key=obj.agent_key,
                    context_epoch=epoch,
                    session_id=f'sess_{uuid4_str().replace("-", "")[:24]}',
                ),
            )
            await db.flush()

        # §9.3:每会话至多一个生成中 run
        active = await ai_run_dao.get_active_by_session(db, conv.session_id)
        if active is not None:
            raise errors.ConflictError(msg='该会话已有生成中的 run,请等待回调或取消')

        # D0 结论:无历史注入接口 → 平台侧把最近已发送上下文内嵌进本条消息
        context_src = obj.context_override if obj.context_override is not None else (conv.context_messages or [])
        context = context_src[-obj.context_max_messages :]
        lines = [f'[Context — epoch {conv.context_epoch}, last {len(context)} messages]']
        lines += [f'- {m.get("sender", "?")}: {m.get("text", "")}' for m in context]
        lines.append('[Trigger]')
        lines.append(f'{obj.sender_name}: {obj.text}')
        message = [{'type': 'Plain', 'text': '\n'.join(lines)}]

        deferred = defer and binding.engine == 'openai'
        countdown = AiService._reply_delay(binding) if deferred and obj.mode != 'script' else 0.0
        refs = obj.source_refs or []
        trigger_source: dict = {
            'refs': refs,
            'text': obj.text,
            'mode': obj.mode,
            'mid': refs[0].get('message_id') if refs else None,
        }
        if obj.mode == 'script':
            trigger_source |= {'script_line': obj.script_line or '', 'rewrite': obj.rewrite}
        if deferred:
            trigger_source |= {'sender_name': obj.sender_name, 'context': context}
        run = await ai_run_dao.create(
            db,
            CreateAiRunParam(
                tenant_id=conv.tenant_id,
                project_id=conv.project_id,
                conversation_id=conv.id,
                session_id=conv.session_id,
                trigger_source=trigger_source,
                idempotency_key=uuid4_str(),
                deadline=timezone.now() + timedelta(seconds=countdown + RUN_DEADLINE_SECONDS),
                context_window={
                    'strategy': 'embedded_in_message',
                    'max_messages': obj.context_max_messages,
                    'injected_count': len(context),
                    'context_epoch': conv.context_epoch,
                },
            ),
        )
        await db.flush()

        if deferred:
            AiService._dispatch_openai(run.id, countdown)
            return run
        if binding.engine == 'openai':
            return await AiService._openai_generate(db, binding, conv, run, obj, context)

        result = await langbot_engine_adapter.submit(
            binding,
            conv.session_id,
            message,
            sender={'id': obj.sender_id or conv.session_id, 'name': obj.sender_name},
            session_type='group',
            idempotency_key=run.idempotency_key,
        )
        if result.ok:
            await ai_run_dao.update_fields(
                db,
                run.id,
                {'status': 'dispatched', 'accepted_message_id': result.accepted_message_id},
            )
            tg_ai_run_active.inc()
            await ai_conversation_dao.update_fields(db, conv.id, {'status': 'locked'})
        elif result.status_code == 409:
            # §9.5:409 不等于成功——按幂等键应能找回原 run;找不到则记 failed 待人工
            await ai_run_dao.update_fields(
                db, run.id, {'status': 'failed', 'last_error': 'idempotent_conflict_unlinked'}
            )
            tg_ai_run_total.labels(status='failed').inc()
        else:
            await ai_run_dao.update_fields(
                db, run.id, {'status': 'failed', 'last_error': result.error or 'submit_failed'}
            )
            tg_ai_run_total.labels(status='failed').inc()
        return await ai_run_dao.get(db, run.id)

    @staticmethod
    async def _resolve_chat_id(db: AsyncSession, account_id: int, value: int | str | None) -> int | None:
        """chat_id 兼容群链接/用户名(同 clone 规则):非纯数字时用绑定账号会话解析。"""
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        if s.lstrip('-').isdigit():
            return int(s)
        account = await telegram_account_dao.get(db, account_id)
        if not account:
            raise errors.NotFoundError(msg='绑定账号不存在')
        results = await join_chat_refs(account, [s])
        r = results.get(s)
        if not r or not r.get('ok'):
            status = ((r or {}).get('error') or {}).get('status', 'resolve_failed')
            raise errors.RequestError(msg=f'群 {s}: {JOIN_ERR.get(status, "进群/解析失败")}')
        return int(r['chat_id'])

    @staticmethod
    async def create_binding(*, db: AsyncSession, obj: CreateAiBindingParam):
        """provider_key 明文只进不出:加密进 provider_key_enc,API 永不回显。"""
        fields = obj.model_dump(exclude={'provider_key'})
        fields['chat_id'] = await AiService._resolve_chat_id(db, obj.account_id, obj.chat_id)
        if obj.provider_key:
            fields['provider_key_enc'] = _provider_cipher().encrypt(obj.provider_key)
        binding = TgAiBinding(**fields)
        db.add(binding)
        await db.flush()
        return binding

    @staticmethod
    async def update_binding(*, db: AsyncSession, pk: int, obj: UpdateAiBindingParam):
        binding = await ai_binding_dao.get(db, pk)
        if not binding:
            raise errors.NotFoundError(msg='绑定不存在')
        fields = obj.model_dump(exclude_unset=True, exclude={'provider_key'})
        if 'chat_id' in fields:
            fields['chat_id'] = await AiService._resolve_chat_id(
                db, obj.account_id or binding.account_id, fields['chat_id']
            )
        if obj.provider_key:
            fields['provider_key_enc'] = _provider_cipher().encrypt(obj.provider_key)
        if fields:
            await ai_binding_dao.update_fields(db, pk, fields)
        return await ai_binding_dao.get(db, pk)

    @staticmethod
    async def delete_binding(*, db: AsyncSession, pk: int) -> int:
        binding = await ai_binding_dao.get(db, pk)
        if not binding:
            raise errors.NotFoundError(msg='绑定不存在')
        return await ai_binding_dao.delete(db, pk)

    @staticmethod
    def _decrypt(enc: str | None) -> str | None:
        if not enc:
            return None
        try:
            return _provider_cipher().decrypt(enc)
        except Exception:
            return None

    @staticmethod
    async def _openai_generate(
        db: AsyncSession,
        binding: TgAiBinding,
        conv: TgAiConversation,
        run: TgAiRun,
        obj: AiTriggerParam,
        context: list,
    ) -> TgAiRun:
        """OpenAI 兼容引擎:同步生成 → 直接产候选进审批链(§9 复用)。"""
        # 发言延迟:模拟真人看消息再回;run 挂 pending/dispatched 期间会话锁定,
        # 新来的消息自然排队(重复消息不会并发触发第二个生成)
        delay = AiService._reply_delay(binding)
        if delay > 0:
            await asyncio.sleep(delay)
        group = await AiService._member_group(db, binding)
        return await AiService._openai_execute(db, binding, conv, run, obj.sender_name, obj.text, context, [], group)

    @staticmethod
    def _reply_delay(binding: TgAiBinding) -> float:
        delay = binding.reply_delay_s or 0
        return random.uniform(delay * 0.7, delay * 1.3) if delay > 0 else 0.0

    @staticmethod
    def _dispatch_openai(run_id: int, countdown: float) -> None:
        celery_app.send_task(OPENAI_GENERATE_TASK, args=[run_id], countdown=max(countdown, MIN_DISPATCH_COUNTDOWN_S))

    @staticmethod
    async def _member_group(db: AsyncSession, binding: TgAiBinding) -> TgAiGroup | None:
        return await ai_group_dao.get(db, binding.group_id) if binding.group_id else None

    @staticmethod
    async def run_deferred_openai(*, db: AsyncSession, run_id: int) -> str:
        """Celery 侧执行延迟生成;run 已被取消/清扫、成员或任务已停用时直接放弃。"""
        run = await ai_run_dao.get(db, run_id)
        if run is None:
            return 'missing'
        if run.status != 'pending':
            return f'skipped:{run.status}'
        conv = await ai_conversation_dao.get(db, run.conversation_id)
        binding = await ai_binding_dao.get(db, conv.binding_id) if conv else None
        group = await AiService._member_group(db, binding) if binding else None
        if (
            conv is None
            or binding is None
            or binding.status != 'active'
            or (binding.group_id is not None and (group is None or group.status != 'active'))
        ):
            await ai_run_dao.update_fields(
                db, run.id, {'status': 'cancelled', 'last_error': 'binding_inactive', 'completed_at': timezone.now()}
            )
            if conv is not None:
                await AiService._unlock_conversation(db, conv.id)
            return 'cancelled'
        src = run.trigger_source or {}
        mid = src.get('mid')
        cache = list((group.recent_messages if group else binding.recent_messages) or [])
        n_ctx = (group.context_max_messages if group else binding.context_max_messages) or 0
        idx = next((i for i, m in enumerate(cache) if mid is not None and m.get('mid') == mid), None)
        if src.get('mode', 'reply') != 'reply':
            before, after = (cache[-n_ctx:] if n_ctx else []), []
        elif idx is None:
            before, after = src.get('context') or [], []
        else:
            before = cache[:idx][-n_ctx:] if n_ctx else []
            after = cache[idx + 1 :]
        stale_max = group.stale_max_messages if group else 0
        if src.get('mode', 'reply') == 'reply' and stale_max and len(after) >= stale_max:
            await ai_run_dao.update_fields(
                db, run.id, {'status': 'cancelled', 'last_error': 'stale', 'completed_at': timezone.now()}
            )
            await AiService._unlock_conversation(db, conv.id)
            return 'stale'
        run = await AiService._openai_execute(
            db, binding, conv, run, src.get('sender_name') or 'User', src.get('text') or '', before, after, group
        )
        return run.status

    @staticmethod
    def _provider(binding: TgAiBinding, group: TgAiGroup | None) -> tuple[str, str | None, str | None]:
        """成员单独配了 key+模型就用成员的,否则用群任务的。"""
        if (binding.provider_key_enc and binding.provider_model) or group is None:
            base = binding.base_url or (group.base_url if group else '')
            return base, AiService._decrypt(binding.provider_key_enc), binding.provider_model
        return group.base_url, AiService._decrypt(group.provider_key_enc), group.provider_model

    @staticmethod
    async def _member_nicks(db: AsyncSession, group: TgAiGroup | None) -> dict[int, str]:
        """本群成员账号 Telegram 用户 ID → 群里显示的昵称(取最近上报的名字,缺省用户名)。"""
        if group is None:
            return {}
        rows = await db.execute(
            sa
            .select(TgTelegramAccount.telegram_user_id, TgTelegramAccount.username)
            .join(TgAiBinding, TgAiBinding.account_id == TgTelegramAccount.id)
            .where(TgAiBinding.group_id == group.id, TgAiBinding.deleted == 0)
        )
        nicks = {uid: name or str(uid) for uid, name in rows if uid is not None}
        for m in group.recent_messages or []:
            if m.get('sid') in nicks and m.get('sender'):
                nicks[m['sid']] = m['sender']
        return nicks

    @staticmethod
    async def _group_system(db: AsyncSession, binding: TgAiBinding, group: TgAiGroup) -> str:
        nicks = await AiService._member_nicks(db, group)
        self_uid = await AiService._account_uid(db, binding.account_id)
        me = nicks.get(self_uid) if self_uid is not None else None
        parts = [f'你是这个 Telegram 群里的一名群成员{f"(群里显示的昵称是「{me}」)" if me else ""}。']
        if binding.role_name:
            parts.append(f'你的角色:{binding.role_name}')
        if group.theme:
            parts.append(f'群主题/背景:{group.theme}')
        parts.append(f'你的人设:{binding.persona or DEFAULT_PERSONA}')
        peers = [n for uid, n in nicks.items() if uid != self_uid]
        if peers:
            parts.append(f'群里的{"、".join(peers)}和你是一伙的:不要互相拆台、不要重复他们刚说过的话,可以自然呼应。')
        limit = f',不超过 {group.max_reply_chars} 字' if group.max_reply_chars else ''
        parts.append(
            f'要求:口语化、简短{limit};不要承认自己是 AI;不要输出括号动作描述;'
            '聊天记录里的「[发言人]」只是标注,回复里不要写任何人的名字、用户名或 @,也不要加「名字:」前缀;'
            '只输出要发到群里的那一句话。'
        )
        return '\n'.join(parts)

    @staticmethod
    async def _build_messages(
        db: AsyncSession,
        binding: TgAiBinding,
        group: TgAiGroup | None,
        run: TgAiRun,
        sender_name: str,
        text: str,
        context: list,
        after: list,
    ) -> list[dict]:
        src = run.trigger_source or {}
        mode = src.get('mode', 'reply')
        if group is None:
            system = binding.persona or DEFAULT_PERSONA
        else:
            system = await AiService._group_system(db, binding, group)
        if after:
            system += f'\n\n群里在这之后又有新消息,请针对{AiService._line(sender_name, text)}这条自然接话。'
        self_uid = await AiService._account_uid(db, binding.account_id)

        def line(m: dict) -> str:
            return AiService._line(m.get('sender', '?'), m.get('text', ''))

        messages = [{'role': 'system', 'content': system}]
        for m in context:
            if self_uid is not None and m.get('sid') == self_uid:
                messages.append({'role': 'assistant', 'content': m.get('text', '')})
            else:
                messages.append({'role': 'user', 'content': line(m)})
        if mode == 'warmup':
            messages.append({
                'role': 'user',
                'content': '(群里有一阵子没人说话了。请围绕群主题自然地开个新话题或随口聊一句,不要提到冷场。)',
            })
        elif mode == 'script':
            messages.append({
                'role': 'user',
                'content': '(用你的口吻改写下面这句话发到群里,意思不变,只输出改写后的内容:'
                f'{src.get("script_line", "")})',
            })
        else:
            messages.append({'role': 'user', 'content': AiService._line(sender_name, text)})
            messages += [{'role': 'user', 'content': line(m)} for m in after]
        return messages

    @staticmethod
    def _line(sender: str, text: str) -> str:
        return f'[{sender}] {text}'

    @staticmethod
    def _strip_names(out: str, names: list[str]) -> str:
        """去掉回复开头的 [名字] / @名字 / 名字: / 名字, 等称呼,只留正文。"""
        names = sorted({n.strip().lstrip('@') for n in names if n and n.strip().lstrip('@')}, key=len, reverse=True)
        if not names:
            return out
        alt = '|'.join(re.escape(n) for n in names)
        pat = re.compile(rf'^\s*(?:\[(?:{alt})\]|@?(?:{alt})(?![A-Za-z0-9_]))[\s:：,，、!！~～]*', re.IGNORECASE)
        cleaned = out
        while True:
            nxt = pat.sub('', cleaned, count=1)
            if nxt == cleaned:
                break
            cleaned = nxt
        return cleaned.strip() or out

    @staticmethod
    async def _account_uid(db: AsyncSession, account_id: int) -> int | None:
        return (
            await db.execute(sa.select(TgTelegramAccount.telegram_user_id).where(TgTelegramAccount.id == account_id))
        ).scalar()

    @staticmethod
    def _gate(group: TgAiGroup | None, binding: TgAiBinding, text: str, mode: str) -> tuple[str, str | None]:
        """内容闸门:清洗名字前缀/引号 → 空/超长/黑名单/近期重复。返回 (清洗后文本, 拒绝原因)。"""
        out = (text or '').strip()
        if binding.role_name:
            for sep in (':', ':'):
                if out.startswith(binding.role_name + sep):
                    out = out[len(binding.role_name) + 1 :].strip()
        if len(out) >= 2 and out[0] in '"“「' and out[-1] in '"”」':
            out = out[1:-1].strip()
        if not out:
            return out, 'empty'
        if group is None:
            return out, None
        if group.punct_space_prob and random.random() * 100 < group.punct_space_prob:
            out = _strip_punct(out)
            if not out:
                return out, 'empty'
        return out, AiService._gate_reason(group, out, mode)

    @staticmethod
    def _gate_reason(group: TgAiGroup, out: str, mode: str) -> str | None:
        if group.max_reply_chars and len(out) > group.max_reply_chars * 2:
            return 'too_long'
        low = out.lower()
        for w in group.blocked_words or []:
            if w and w.strip() and w.strip().lower() in low:
                return f'blocked_word:{w.strip()[:30]}'
        if mode != 'script':
            norm = _norm(low)
            if norm and any(_norm(str(m.get('text', '')).lower()) == norm for m in (group.recent_messages or [])[-50:]):
                return 'duplicate'
        return None

    @staticmethod
    async def _fail_run(db: AsyncSession, run: TgAiRun, conv: TgAiConversation, err: str) -> TgAiRun:
        await ai_run_dao.update_fields(db, run.id, {'status': 'failed', 'last_error': err[:255]})
        tg_ai_run_total.labels(status='failed').inc()
        await AiService._unlock_conversation(db, conv.id)
        return await ai_run_dao.get(db, run.id)

    @staticmethod
    async def _openai_execute(
        db: AsyncSession,
        binding: TgAiBinding,
        conv: TgAiConversation,
        run: TgAiRun,
        sender_name: str,
        text: str,
        context: list,
        after: list | None = None,
        group: TgAiGroup | None = None,
    ) -> TgAiRun:
        src = run.trigger_source or {}
        mode = src.get('mode', 'reply')
        base_url, api_key, model = AiService._provider(binding, group)
        if mode == 'script' and not src.get('rewrite'):
            ok, out, err = True, str(src.get('script_line') or ''), None
        else:
            if not api_key or not base_url or not model:
                return await AiService._fail_run(db, run, conv, 'provider_not_configured')
            messages = await AiService._build_messages(db, binding, group, run, sender_name, text, context, after or [])
            ok, out, err = await openai_complete(base_url=base_url, api_key=api_key, model=model, messages=messages)
        await db.refresh(run, attribute_names=['status'])
        if run.status != 'pending':
            return run
        if not ok:
            return await AiService._fail_run(db, run, conv, err or 'generate_failed')
        if mode == 'reply':
            seen = [*context, *(after or [])]
            nicks = await AiService._member_nicks(db, group)
            out = AiService._strip_names(
                out,
                [sender_name, binding.role_name or '', *nicks.values(), *(m.get('sender', '') for m in seen)],
            )
        out, reason = AiService._gate(group, binding, out, mode)
        if reason:
            return await AiService._fail_run(db, run, conv, f'gate:{reason}')
        quote_to = None
        if mode == 'reply' and group is not None and src.get('mid') and random.randint(1, 100) <= group.quote_prob:
            quote_to = int(src['mid'])
        candidate = await AiService._create_candidate(
            db, run, conv, out, binding=binding, group=group, reply_to=quote_to
        )
        await ai_run_dao.update_fields(
            db,
            run.id,
            {
                'status': 'completed',
                'candidate_id': candidate.id,
                'completed_at': timezone.now(),
                'usage': {'model': model, 'mode': mode},
            },
        )
        tg_ai_run_total.labels(status='completed').inc()
        await AiService._unlock_conversation(db, conv.id)
        return await ai_run_dao.get(db, run.id)

    @staticmethod
    def _cst_hour(now: datetime) -> int:
        return (now.astimezone(UTC) + timedelta(hours=8)).hour

    @staticmethod
    def in_active_hours(group: TgAiGroup, now: datetime) -> bool:
        """活跃时段按北京时间;开始=结束表示全天,开始>结束表示跨夜(如 20-2)。"""
        start, end = group.active_start_hour, group.active_end_hour
        if start == end:
            return True
        h = AiService._cst_hour(now)
        return start <= h < end if start < end else (h >= start or h < end)

    @staticmethod
    async def _find_group(
        db: AsyncSession, account: TgTelegramAccount, chat_id: int, topic_id: int | None
    ) -> TgAiGroup | None:
        groups = await ai_group_dao.get_all(db, tenant_id=account.tenant_id, project_id=account.project_id)
        hit = next(
            (
                g
                for g in groups
                if AiService._chat_match(g.chat_id, chat_id) and (g.topic_id or None) == (topic_id or None)
            ),
            None,
        )
        if hit is None:
            return None
        return (
            await db.execute(
                sa
                .select(TgAiGroup)
                .where(TgAiGroup.id == hit.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

    @staticmethod
    async def handle_group_event(
        *, db: AsyncSession, obj: AiGroupEventParam, account: TgTelegramAccount, username: str | None
    ) -> int:
        """worker 上报的群/私信消息。群消息:锁任务行 → 按 message_id 去重写入群缓存 → 统一挑号接话。

        同群多号会各自上报同一条消息,任务行锁 + 缓存去重保证每条只决策一次;
        托管号(自己人)发的消息默认只进缓存,开了「号之间互聊」才按轮数上限接一轮。返回触发的 run 数。"""
        del username
        if obj.chat_class == 'private':
            return await AiService.handle_private_event(db=db, obj=obj, account=account)
        group = await AiService._find_group(db, account, obj.chat_id, obj.topic_id)
        if group is None:
            return 0
        managed = await AiService._managed_user_ids(db, account.tenant_id)
        is_ours = obj.sender_id is not None and obj.sender_id in managed
        recent = await AiService._record_group_message(db, group, obj, is_ours=is_ours)
        if recent is None or group.status != 'active' or obj.sender_is_bot:
            return 0
        if is_ours and not AiService._chain_allowed(group, recent):
            return 0
        members = await AiService._group_members(db, group)
        chosen = await AiService._pick_speakers(db, group, members, obj, recent, is_ours=is_ours)
        n = 0
        for b in chosen:
            if await AiService._start_member_run(db, group, b, obj=obj, mode='reply'):
                n += 1
        return n

    @staticmethod
    def _chain_allowed(group: TgAiGroup, recent: list[dict]) -> bool:
        """自己人连续发言轮数(含本条)不超过「号之间互聊轮数」;0=自己人发言不触发。"""
        chain = 0
        for m in reversed(recent):
            if not m.get('ours'):
                break
            chain += 1
        return bool(group.bot_chain_max) and chain <= group.bot_chain_max

    @staticmethod
    async def _record_group_message(
        db: AsyncSession, group: TgAiGroup, obj: AiGroupEventParam, *, is_ours: bool
    ) -> list[dict] | None:
        """写入群缓存;同一条已记过(别的号先上报了)返回 None。"""
        recent = list(group.recent_messages or [])
        if any(m.get('mid') == obj.message_id for m in recent):
            return None
        recent.append({
            'sender': obj.sender_name or 'User',
            'text': (obj.text or '')[:500],
            'mid': obj.message_id,
            'sid': obj.sender_id,
            'ours': is_ours,
            'ts': int(timezone.now().timestamp()),
        })
        group.recent_messages = recent[-100:]
        group.last_message_at = timezone.now()
        db.add(group)
        await db.flush()
        return recent

    @staticmethod
    async def _group_members(db: AsyncSession, group: TgAiGroup) -> list[TgAiBinding]:
        rows = await ai_binding_dao.get_all(db, tenant_id=group.tenant_id, project_id=group.project_id)
        return [b for b in rows if b.group_id == group.id and b.status == 'active']

    @staticmethod
    async def _start_member_run(
        db: AsyncSession,
        group: TgAiGroup,
        b: TgAiBinding,
        *,
        obj: AiGroupEventParam | None = None,
        mode: str = 'reply',
        script_line: str | None = None,
        rewrite: bool = False,
    ) -> bool:
        try:
            async with db.begin_nested():
                await AiService.trigger(
                    db=db,
                    obj=AiTriggerParam(
                        binding_id=b.id,
                        chat_id=group.chat_id,
                        topic_id=group.topic_id,
                        agent_key=f'binding:{b.id}',
                        text=(obj.text if obj else '') or '',
                        sender_name=(obj.sender_name if obj else '') or '',
                        sender_id=str(obj.sender_id) if obj and obj.sender_id else None,
                        source_refs=[{'chat_id': obj.chat_id, 'message_id': obj.message_id}] if obj else [],
                        context_max_messages=group.context_max_messages,
                        context_override=[],
                        mode=mode,
                        script_line=script_line,
                        rewrite=rewrite,
                    ),
                    defer=True,
                )
        except (errors.RequestError, errors.ConflictError, errors.NotFoundError, IntegrityError):
            return False
        return True

    @staticmethod
    async def _member_stats(
        db: AsyncSession, group: TgAiGroup, members: list[TgAiBinding]
    ) -> tuple[dict[int, TgTelegramAccount], dict[int, sa.Row]]:
        accounts = {
            a.id: a
            for a in (
                await db.execute(
                    sa.select(TgTelegramAccount).where(
                        TgTelegramAccount.id.in_([b.account_id for b in members] or [0]),
                        TgTelegramAccount.deleted == 0,
                        TgTelegramAccount.desired_status == 'running',
                    )
                )
            ).scalars()
        }
        now = timezone.now()
        since = now - timedelta(seconds=max(3600, group.account_cooldown_s))
        hour_ago = now - timedelta(hours=1)
        stats = {
            row.binding_id: row
            for row in await db.execute(
                sa
                .select(
                    TgAiConversation.binding_id,
                    sa.func.max(TgAiRun.created_time).label('last_at'),
                    sa.func.count().filter(TgAiRun.created_time >= hour_ago).label('hour_n'),
                    sa.func.count().filter(TgAiRun.status.in_(ACTIVE_RUN_STATUSES)).label('active_n'),
                )
                .join(TgAiConversation, TgAiConversation.id == TgAiRun.conversation_id)
                .where(
                    TgAiConversation.binding_id.in_([b.id for b in members] or [0]),
                    TgAiRun.status.not_in(('cancelled', 'failed')),
                    TgAiRun.created_time >= since,
                )
                .group_by(TgAiConversation.binding_id)
            )
        }
        return accounts, stats

    @staticmethod
    async def _pick_speakers(
        db: AsyncSession,
        group: TgAiGroup,
        members: list[TgAiBinding],
        obj: AiGroupEventParam,
        recent: list[dict],
        *,
        is_ours: bool,
    ) -> list[TgAiBinding]:
        """被 @ / 被回复的号必回;其余按活跃度掷骰,人数落在并发区间;不够最少人数时从活跃度>0 的号里补。

        自己人发的消息(互聊)只挑一个号接,且不会是发言者本人。非活跃时段只有被点名才回(可配置)。"""
        if not members:
            return []
        accounts, stats = await AiService._member_stats(db, group, members)
        now = timezone.now()
        text = (obj.text or '').lower()
        replied_sid = next(
            (m.get('sid') for m in recent if obj.reply_to_message_id and m.get('mid') == obj.reply_to_message_id),
            None,
        )
        buckets: dict[str, list[TgAiBinding]] = {'forced': [], 'activated': [], 'rest': []}
        for b in members:
            acc = accounts.get(b.account_id)
            if acc is None or (is_ours and acc.telegram_user_id == obj.sender_id):
                continue
            if AiService._speaker_blocked(stats.get(b.id), group, now):
                continue
            called = (bool(acc.username) and f'@{acc.username}'.lower() in text) or (
                replied_sid is not None and replied_sid == acc.telegram_user_id
            )
            if called:
                buckets['forced'].append(b)
            elif b.random_prob > 0:
                buckets['activated' if random.randint(1, 100) <= b.random_prob else 'rest'].append(b)
        forced, activated, rest = buckets['forced'], buckets['activated'], buckets['rest']
        if not AiService.in_active_hours(group, now):
            return forced if group.mention_bypass_hours and not is_ours else []
        random.shuffle(activated)
        random.shuffle(rest)
        if is_ours:
            pool = forced + activated + rest
            return pool[:1]
        want = random.randint(max(1, group.reply_min), max(1, group.reply_min, group.reply_max))
        chosen = forced + activated[: max(0, want - len(forced))]
        if len(chosen) < group.reply_min:
            chosen += rest[: group.reply_min - len(chosen)]
        return chosen

    @staticmethod
    def _speaker_blocked(st: sa.Row | None, group: TgAiGroup, now: datetime) -> bool:
        """生成中 / 冷却中 / 已达小时上限。"""
        if st is None:
            return False
        if st.active_n:
            return True
        if group.account_cooldown_s and st.last_at > now - timedelta(seconds=group.account_cooldown_s):
            return True
        return bool(group.account_hourly_max and st.hour_n >= group.account_hourly_max)

    @staticmethod
    async def warmup_tick(db: AsyncSession) -> int:
        """冷场暖场:群里 X 分钟没人说话(含上次暖场)且在活跃时段 → 按活跃度加权挑一个号抛话题。"""
        now = timezone.now()
        groups = (
            (
                await db.execute(
                    sa
                    .select(TgAiGroup)
                    .where(TgAiGroup.deleted == 0, TgAiGroup.status == 'active', TgAiGroup.idle_warmup_min > 0)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        n = 0
        for g in groups:
            if await AiService.warmup_group(db, g, now=now):
                n += 1
        return n

    @staticmethod
    async def warmup_group(db: AsyncSession, g: TgAiGroup, *, now: datetime, force: bool = False) -> bool:
        if not force:
            if not AiService.in_active_hours(g, now):
                return False
            last = max(x for x in (g.last_message_at, g.last_warmup_at, g.created_time) if x is not None)
            if now - last < timedelta(minutes=g.idle_warmup_min):
                return False
        members = await AiService._group_members(db, g)
        accounts, stats = await AiService._member_stats(db, g, members)
        pool = [
            b
            for b in members
            if b.account_id in accounts
            and b.random_prob > 0
            and not AiService._speaker_blocked(stats.get(b.id), g, now)
        ]
        if not pool:
            return False
        g.last_warmup_at = now
        db.add(g)
        speaker = random.choices(pool, weights=[b.random_prob for b in pool], k=1)[0]
        return await AiService._start_member_run(db, g, speaker, mode='warmup')

    @staticmethod
    async def script_step(db: AsyncSession, script_id: int, token: str) -> str:
        """剧本执行一步:按 cursor 由指定成员发一句(可 AI 改写),再按间隔排下一步;播完/停止/令牌不符即止。"""
        script = (
            await db.execute(
                sa.select(TgAiScript).where(TgAiScript.id == script_id, TgAiScript.deleted == 0).with_for_update()
            )
        ).scalar_one_or_none()
        if script is None or script.status != 'running' or script.run_token != token:
            return 'stopped'
        group = await ai_group_dao.get(db, script.group_id)
        lines = list(script.lines or [])
        if group is None or group.status != 'active' or script.cursor >= len(lines):
            script.status, script.run_token = 'idle', None
            db.add(script)
            return 'done'
        line = lines[script.cursor]
        member = next((b for b in await AiService._group_members(db, group) if b.id == line.get('member_id')), None)
        started = member is not None and await AiService._start_member_run(
            db, group, member, mode='script', script_line=str(line.get('text') or ''), rewrite=script.rewrite
        )
        if member is not None and not started:
            AiService._dispatch_script(script.id, token, 10)
            return 'retry'
        script.cursor += 1
        db.add(script)
        if script.cursor >= len(lines):
            script.status, script.run_token = 'idle', None
            return 'done'
        AiService._dispatch_script(script.id, token, random.uniform(script.interval_s * 0.7, script.interval_s * 1.3))
        return 'next'

    @staticmethod
    def _dispatch_script(script_id: int, token: str, countdown: float) -> None:
        celery_app.send_task(SCRIPT_STEP_TASK, args=[script_id, token], countdown=max(countdown, 1))

    @staticmethod
    async def handle_private_event(*, db: AsyncSession, obj: AiGroupEventParam, account: TgTelegramAccount) -> int:
        """私信:按账号配置自动回复(同一人冷却内只回一次)并/或转发给业务号/群;都走发送队列 + worker SendPolicy。"""
        if obj.sender_id is None or obj.sender_is_bot or obj.sender_id == account.telegram_user_id:
            return 0
        cfg = next(iter(await ai_private_reply_dao.get_all(db, account_id=account.id)), None)
        if cfg is None or not cfg.enabled or cfg.tenant_id != account.tenant_id:
            return 0
        if obj.sender_id in await AiService._managed_user_ids(db, account.tenant_id):
            return 0
        claimed = await redis_client.set(
            f'tg:ai:pm:{account.id}:{obj.chat_id}:{obj.message_id}', 1, nx=True, ex=GROUP_EVENT_CLAIM_TTL_S
        )
        if not claimed:
            return 0
        n = 0
        if cfg.reply_text and cfg.reply_text.strip():
            ok = True
            if cfg.reply_cooldown_min:
                ok = bool(
                    await redis_client.set(
                        f'tg:ai:pm_cd:{account.id}:{obj.sender_id}', 1, nx=True, ex=cfg.reply_cooldown_min * 60
                    )
                )
            if ok:
                await AiService._direct_send(db, account, obj.chat_id, cfg.reply_text.strip())
                n += 1
        if cfg.forward_chat_id:
            body = f'[私信] {obj.sender_name}({obj.sender_id}):\n{(obj.text or "")[:1500]}'
            await AiService._direct_send(db, account, cfg.forward_chat_id, body)
            n += 1
        return n

    @staticmethod
    async def _direct_send(db: AsyncSession, account: TgTelegramAccount, chat_id: int, text: str) -> None:
        """配置型自动发送(私信回复/转发):候选 + 已通过审批 → 发送队列。"""
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        expires = timezone.now() + timedelta(hours=CANDIDATE_TTL_HOURS)
        candidate = await reply_candidate_dao.create(
            db,
            CreateReplyCandidateParam(
                tenant_id=account.tenant_id,
                project_id=account.project_id,
                account_id=account.id,
                target_chat_id=chat_id,
                content=text,
                content_hash=content_hash,
                expires_at=expires,
            ),
        )
        await db.flush()
        approval = await approval_dao.create(
            db,
            CreateApprovalParam(
                tenant_id=account.tenant_id,
                project_id=account.project_id,
                candidate_id=candidate.id,
                candidate_version=candidate.version,
                content_hash=content_hash,
                expires_at=expires,
                status='approved',
                decided_at=timezone.now(),
                reason='私信自动回复/转发',
            ),
        )
        await db.flush()
        await reply_candidate_dao.update_status(db, candidate.id, 'approved')
        await ApprovalService._create_send_job(db, approval, candidate)

    @staticmethod
    async def _managed_user_ids(db: AsyncSession, tenant_id: int) -> set[int]:
        rows = await db.execute(
            sa.select(TgTelegramAccount.telegram_user_id).where(
                TgTelegramAccount.tenant_id == tenant_id,
                TgTelegramAccount.deleted == 0,
                TgTelegramAccount.telegram_user_id.is_not(None),
            )
        )
        return set(rows.scalars())

    @staticmethod
    def _chat_match(binding_chat: int, event_chat: int) -> bool:
        """chat_id 等值匹配,兼容 -100 前缀差异。"""
        if binding_chat == event_chat:
            return True
        norm = abs(binding_chat) % 10**15 if abs(binding_chat) > 10**10 else abs(binding_chat)
        en = abs(event_chat) % 10**15 if abs(event_chat) > 10**10 else abs(event_chat)
        return norm == en

    @staticmethod
    async def handle_callback(*, db: AsyncSession, binding_uuid: str, raw_body: bytes, headers: dict[str, str]) -> str:
        """验证签名→落库(去重)→关联 run→final 且序连续→产候选+审批。

        返回 'ok' | 'dedup';抛错则由 API 层决定 HTTP 码。
        """
        binding = await ai_binding_dao.get_by_uuid(db, binding_uuid)
        if not binding or binding.status != 'active':
            raise errors.NotFoundError(msg='AI 绑定不存在')

        ok, reason = verify_callback_signature(
            secret=resolve_secret(binding.outbound_secret_ref),
            body=raw_body,
            timestamp=headers.get('x-lb-timestamp'),
            signature=headers.get('x-lb-signature'),
        )
        if not ok:
            tg_ai_callback_total.labels(result='rejected').inc()
            raise errors.RequestError(msg=f'回调签名无效: {reason}')

        try:
            payload: dict[str, Any] = json.loads(raw_body)
        except json.JSONDecodeError:
            raise errors.RequestError(msg='回调体不是合法 JSON')

        session_id = str(payload.get('session_id') or '')
        reply_to = str(payload.get('reply_to') or '')
        sequence = int(payload.get('sequence') or 0)
        is_final = bool(payload.get('is_final'))
        if not session_id or not reply_to or sequence < 1:
            raise errors.RequestError(msg='回调缺 session_id/reply_to/sequence')

        sha = hashlib.sha256(raw_body).hexdigest()
        run = await AiService._link_run(db, session_id, reply_to)
        callback_obj = CreateAiCallbackParam(
            binding_id=binding.id,
            session_id=session_id,
            reply_to=reply_to,
            sequence=sequence,
            is_final=is_final,
            payload=payload,
            payload_sha256=sha,
            received_at=timezone.now(),
            ai_run_id=run.id if run else None,
            link_status='linked' if run else 'pending_link',
        )
        try:
            cb = await ai_callback_dao.create(db, callback_obj)
            await db.flush()
        except IntegrityError:
            await db.rollback()
            tg_ai_callback_total.labels(result='dedup').inc()
            return 'dedup'

        if run is not None:
            await AiService._advance_run(db, run, cb)
            tg_ai_callback_total.labels(result='linked').inc()
        else:
            tg_ai_callback_total.labels(result='pending_link').inc()
        return 'ok'

    @staticmethod
    async def _link_run(db: AsyncSession, session_id: str, reply_to: str) -> TgAiRun | None:
        """reply_to == LangBot 返回的 accepted_message_id;退化按 session 活动 run 关联。"""
        conv = await ai_conversation_dao.get_by_session(db, session_id)
        if conv is None:
            return None
        runs = await ai_run_dao.get_all(db, tenant_id=conv.tenant_id)
        for r in runs:
            if (
                r.session_id == session_id
                and r.status in ('dispatched', 'running', 'pending')
                and (r.accepted_message_id == reply_to or r.accepted_message_id is None)
            ):
                return r
        return None

    @staticmethod
    async def _advance_run(db: AsyncSession, run: TgAiRun, cb: TgAiCallback) -> None:
        """推进 run:序校验 → final 时组文本 → 产候选/审批。"""
        if cb.sequence != run.expected_seq:
            # 缺段:等重试回填;若本条已是 final 则直接 incomplete(§9.3 不发半截)
            if cb.is_final:
                await ai_run_dao.update_fields(
                    db,
                    run.id,
                    {
                        'status': 'incomplete',
                        'last_error': f'gap: expected_seq={run.expected_seq}, got {cb.sequence}',
                        'completed_at': timezone.now(),
                    },
                )
                tg_ai_run_total.labels(status='incomplete').inc()
                tg_ai_run_active.dec()
                await AiService._unlock_conversation(db, run.conversation_id)
            return

        fields: dict[str, Any] = {
            'expected_seq': cb.sequence + 1,
            'status': 'running',
        }
        if cb.is_final:
            parts = cb.payload.get('message') or []
            text = '\n'.join(
                p.get('text', '') for p in parts if isinstance(p, dict) and p.get('type') == 'Plain'
            ).strip()
            all_cbs = list(await ai_callback_dao.get_all_for_run(db, run.id))
            full_text = AiService._assemble(all_cbs, fallback=text)
            conv = await ai_conversation_dao.get(db, run.conversation_id)
            candidate = await AiService._create_candidate(db, run, conv, full_text)
            fields.update({
                'status': 'completed',
                'candidate_id': candidate.id,
                'completed_at': timezone.now(),
            })
            tg_ai_run_total.labels(status='completed').inc()
            tg_ai_run_active.dec()
        await ai_run_dao.update_fields(db, run.id, fields)
        if cb.is_final:
            await AiService._unlock_conversation(db, run.conversation_id)

    @staticmethod
    def _assemble(callbacks: list[TgAiCallback], *, fallback: str) -> str:
        """按 sequence 拼接各分段 Plain 文本(每段可含多 part)。"""
        ordered = sorted(callbacks, key=lambda c: c.sequence)
        texts: list[str] = []
        for c in ordered:
            texts.extend(
                p['text']
                for p in c.payload.get('message') or []
                if isinstance(p, dict) and p.get('type') == 'Plain' and p.get('text')
            )
        return '\n'.join(texts).strip() or fallback

    @staticmethod
    async def _create_candidate(
        db: AsyncSession,
        run: TgAiRun,
        conv: TgAiConversation,
        text: str,
        binding: TgAiBinding | None = None,
        group: TgAiGroup | None = None,
        reply_to: int | None = None,
    ) -> TgReplyCandidate:
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        expires = timezone.now() + timedelta(hours=CANDIDATE_TTL_HOURS)
        candidate = await reply_candidate_dao.create(
            db,
            CreateReplyCandidateParam(
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                account_id=conv.account_id,
                target_chat_id=conv.chat_id,
                target_topic_id=conv.topic_id,
                content=text,
                content_hash=content_hash,
                expires_at=expires,
                agent_run_id=run.uuid,
                reply_to_source_id=reply_to,
            ),
        )
        await db.flush()
        auto = bool(group.auto_approve) if group is not None else bool(binding and binding.auto_approve)
        approval = await approval_dao.create(
            db,
            CreateApprovalParam(
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                candidate_id=candidate.id,
                candidate_version=candidate.version,
                content_hash=content_hash,
                expires_at=expires,
                status='approved' if auto else 'pending',
                decided_at=timezone.now() if auto else None,
            ),
        )
        await db.flush()
        if auto:
            await reply_candidate_dao.update_status(db, candidate.id, 'approved')
            await ApprovalService._create_send_job(db, approval, candidate)
        return candidate

    @staticmethod
    async def _unlock_conversation(db: AsyncSession, conversation_id: int) -> None:
        await ai_conversation_dao.update_fields(db, conversation_id, {'status': 'open'})

    @staticmethod
    async def cancel_run(*, db: AsyncSession, pk: int) -> TgAiRun:
        """平台侧取消(§9.6):阻止回调进发送,不承诺远端停止。"""
        run = await ai_run_dao.get(db, pk)
        if not run:
            raise errors.NotFoundError(msg='run 不存在')
        if run.status not in ('pending', 'dispatched', 'running'):
            raise errors.RequestError(msg='run 已结束')
        await ai_run_dao.update_fields(db, run.id, {'status': 'cancelled', 'completed_at': timezone.now()})
        tg_ai_run_total.labels(status='cancelled').inc()
        tg_ai_run_active.dec()
        await AiService._unlock_conversation(db, run.conversation_id)
        return await ai_run_dao.get(db, pk)

    @staticmethod
    async def sweep_deadlines(db: AsyncSession) -> int:
        """超时 run → incomplete(§9.5 回调缺失可见)。供 beat 周期任务调用。"""
        runs = await ai_run_dao.get_all(db)
        now = timezone.now()
        n = 0
        for r in runs:
            if r.status in ('dispatched', 'running', 'pending') and r.deadline and r.deadline < now:
                await ai_run_dao.update_fields(
                    db,
                    r.id,
                    {
                        'status': 'incomplete',
                        'last_error': 'callback_deadline_exceeded',
                        'completed_at': now,
                    },
                )
                tg_ai_run_total.labels(status='incomplete').inc()
                tg_ai_run_active.dec()
                await AiService._unlock_conversation(db, r.conversation_id)
                n += 1
        return n


ai_service = AiService()

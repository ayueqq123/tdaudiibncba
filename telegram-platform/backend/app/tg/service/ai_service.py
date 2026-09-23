import asyncio
import hashlib
import json
import random

from datetime import timedelta

from backend.core.conf import settings
from backend.utils.encrypt import ItsDCipher
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tg.crud.crud_ai import (
    ai_binding_dao,
    ai_callback_dao,
    ai_conversation_dao,
    ai_run_dao,
)
from backend.app.tg.crud.crud_approval import approval_dao, reply_candidate_dao
from backend.app.tg.metrics import tg_ai_callback_total, tg_ai_run_active, tg_ai_run_total
from backend.app.tg.model import TgReplyCandidate
from backend.app.tg.model.ai import TgAiBinding, TgAiCallback, TgAiConversation, TgAiRun
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
from backend.app.tg.service.ai_engine import (
    langbot_engine_adapter,
    openai_complete,
    resolve_secret,
    verify_callback_signature,
)
from backend.common.exception import errors
from backend.database.db import uuid4_str
from backend.utils.timezone import timezone

# 回调缺失判定窗口:LangBot 侧回调内存队列不可信(§9.5),到期标 incomplete
RUN_DEADLINE_SECONDS = 180
# 候选有效期:审批 SLA 之外的安全边界
CANDIDATE_TTL_HOURS = 24

DEFAULT_PERSONA = (
    '你是一个群聊里的普通成员,说话自然简短,像真人聊天。'
    '不要承认自己 AI,不要输出括号动作描述,不要长篇大论。'
)


def _provider_cipher() -> ItsDCipher:
    """模型 API key 加解密器:TOKEN_SECRET_KEY 派生 32 字节密钥。"""
    key = hashlib.sha256(settings.TOKEN_SECRET_KEY.encode()).digest()
    return ItsDCipher(key)


class AiService:
    """AI 链路编排(§9.2):trigger → ai_run → LangBot → callback → candidate → approval。"""

    @staticmethod
    async def _current_epoch(db: AsyncSession, binding: TgAiBinding, obj: AiTriggerParam) -> int:
        """取该会话域最新的 context_epoch;新建会话从 0 起。"""
        convs = await ai_conversation_dao.get_all(
            db, tenant_id=binding.tenant_id, project_id=binding.project_id
        )
        return max(
            (
                c.context_epoch
                for c in convs
                if c.chat_id == obj.chat_id
                and c.topic_id == obj.topic_id
                and c.agent_key == obj.agent_key
            ),
            default=0,
        )

    @staticmethod
    async def trigger(*, db: AsyncSession, obj: AiTriggerParam) -> TgAiRun:
        """创建会话(若无)→组装内嵌上下文消息→建 run→提交 LangBot。"""
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
        context = (conv.context_messages or [])[-obj.context_max_messages :]
        lines = [f"[Context — epoch {conv.context_epoch}, last {len(context)} messages]"]
        lines += [f"- {m.get('sender', '?')}: {m.get('text', '')}" for m in context]
        lines.append('[Trigger]')
        lines.append(f'{obj.sender_name}: {obj.text}')
        message = [{'type': 'Plain', 'text': '\n'.join(lines)}]

        run = await ai_run_dao.create(
            db,
            CreateAiRunParam(
                tenant_id=conv.tenant_id,
                project_id=conv.project_id,
                conversation_id=conv.id,
                session_id=conv.session_id,
                trigger_source={'refs': obj.source_refs or [], 'text': obj.text},
                idempotency_key=uuid4_str(),
                deadline=timezone.now() + timedelta(seconds=RUN_DEADLINE_SECONDS),
                context_window={
                    'strategy': 'embedded_in_message',
                    'max_messages': obj.context_max_messages,
                    'injected_count': len(context),
                    'context_epoch': conv.context_epoch,
                },
            ),
        )
        await db.flush()

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
    async def create_binding(*, db: AsyncSession, obj: CreateAiBindingParam):
        """provider_key 明文只进不出:加密进 provider_key_enc,API 永不回显。"""
        fields = obj.model_dump(exclude={'provider_key'})
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
    def _decrypt_provider_key(binding: TgAiBinding) -> str | None:
        if not binding.provider_key_enc:
            return None
        try:
            return _provider_cipher().decrypt(binding.provider_key_enc)
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
        delay = binding.reply_delay_s or 0
        if delay > 0:
            await asyncio.sleep(random.uniform(delay * 0.7, delay * 1.3))

        api_key = AiService._decrypt_provider_key(binding)
        if not api_key or not binding.base_url or not binding.provider_model:
            await ai_run_dao.update_fields(
                db, run.id, {'status': 'failed', 'last_error': 'provider_not_configured'}
            )
            tg_ai_run_total.labels(status='failed').inc()
            await AiService._unlock_conversation(db, conv.id)
            return await ai_run_dao.get(db, run.id)

        messages = [{'role': 'system', 'content': binding.persona or DEFAULT_PERSONA}]
        messages += [
            {'role': 'user', 'content': f"{m.get('sender', '?')}: {m.get('text', '')}"}
            for m in context
        ]
        messages.append({'role': 'user', 'content': f'{obj.sender_name}: {obj.text}'})
        ok, text, err = await openai_complete(
            base_url=binding.base_url,
            api_key=api_key,
            model=binding.provider_model,
            messages=messages,
        )
        if ok:
            candidate = await AiService._create_candidate(db, run, conv, text)
            await ai_run_dao.update_fields(
                db,
                run.id,
                {
                    'status': 'completed',
                    'candidate_id': candidate.id,
                    'completed_at': timezone.now(),
                },
            )
            tg_ai_run_total.labels(status='completed').inc()
        else:
            await ai_run_dao.update_fields(
                db, run.id, {'status': 'failed', 'last_error': err or 'generate_failed'}
            )
            tg_ai_run_total.labels(status='failed').inc()
        await AiService._unlock_conversation(db, conv.id)
        return await ai_run_dao.get(db, run.id)

    @staticmethod
    async def handle_group_event(*, db: AsyncSession, obj: AiGroupEventParam, account, username: str | None) -> int:
        """worker 上报的群消息 → 匹配 openai 绑定 → trigger。返回触发的 run 数。"""
        bindings = await ai_binding_dao.get_all(
            db, tenant_id=account.tenant_id, project_id=account.project_id
        )
        matched = [
            b
            for b in bindings
            if b.engine == 'openai'
            and b.status == 'active'
            and b.chat_id is not None
            and AiService._chat_match(b.chat_id, obj.chat_id)
            and (b.topic_id or None) == (obj.topic_id or None)
        ]
        n = 0
        for b in matched:
            if b.speak_policy == 'mention' and username:
                if f'@{username}' not in (obj.text or ''):
                    continue
            if b.speak_policy == 'random':
                if random.randint(1, 100) > (b.random_prob or 30):
                    continue
            # 上报账号自己发的消息不触发(防自问自答循环)
            if obj.sender_id is not None and obj.sender_id == account.telegram_user_id:
                continue
            try:
                await AiService.trigger(
                    db=db,
                    obj=AiTriggerParam(
                        binding_id=b.id,
                        chat_id=obj.chat_id,
                        topic_id=obj.topic_id,
                        text=obj.text,
                        sender_name=obj.sender_name,
                        sender_id=str(obj.sender_id) if obj.sender_id else None,
                        source_refs=[{'chat_id': obj.chat_id, 'message_id': obj.message_id}],
                        context_max_messages=b.context_max_messages or 12,
                    ),
                )
                n += 1
            except errors.RequestError:
                # 会话域已有活动 run → 让位,不触发重复生成
                continue
        return n

    @staticmethod
    def _chat_match(binding_chat: int, event_chat: int) -> bool:
        """chat_id 等值匹配,兼容 -100 前缀差异。"""
        if binding_chat == event_chat:
            return True
        norm = abs(binding_chat) % 10**15 if abs(binding_chat) > 10**10 else abs(binding_chat)
        en = abs(event_chat) % 10**15 if abs(event_chat) > 10**10 else abs(event_chat)
        return norm == en

    @staticmethod
    async def handle_callback(
        *, db: AsyncSession, binding_uuid: str, raw_body: bytes, headers: dict[str, str]
    ) -> str:
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
            fields.update(
                {
                    'status': 'completed',
                    'candidate_id': candidate.id,
                    'completed_at': timezone.now(),
                }
            )
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
        db: AsyncSession, run: TgAiRun, conv: TgAiConversation, text: str
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
            ),
        )
        await db.flush()
        await approval_dao.create(
            db,
            CreateApprovalParam(
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                candidate_id=candidate.id,
                candidate_version=candidate.version,
                content_hash=content_hash,
                expires_at=expires,
                status='pending',
            ),
        )
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
        await ai_run_dao.update_fields(
            db, run.id, {'status': 'cancelled', 'completed_at': timezone.now()}
        )
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

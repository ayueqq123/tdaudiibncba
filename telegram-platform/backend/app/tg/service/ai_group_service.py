from datetime import timedelta

import sqlalchemy as sa

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tg.crud.crud_ai import (
    ai_binding_dao,
    ai_group_dao,
    ai_persona_dao,
    ai_private_reply_dao,
    ai_script_dao,
)
from backend.app.tg.crud.crud_membership import membership_dao
from backend.app.tg.crud.crud_telegram_account import telegram_account_dao
from backend.app.tg.model import TgReplyCandidate, TgTelegramAccount
from backend.app.tg.model.ai import (
    TgAiBinding,
    TgAiConversation,
    TgAiGroup,
    TgAiPersona,
    TgAiPrivateReply,
    TgAiRun,
    TgAiScript,
)
from backend.app.tg.schema.ai import (
    AiMemberParam,
    AiPersonaParam,
    AiPrivateReplyParam,
    AiScriptParam,
    CreateAiGroupParam,
    GetAiGroupDetail,
    GetAiGroupRunDetail,
    GetAiMemberDetail,
    UpdateAiGroupParam,
)
from backend.app.tg.service.account_service import JOIN_ERR, join_chat_refs
from backend.app.tg.service.ai_service import AiService, _provider_cipher
from backend.common.exception import errors
from backend.database.db import uuid4_str
from backend.utils.timezone import timezone


def _account_label(a: TgTelegramAccount | None) -> str:
    if a is None:
        return '-'
    if a.username:
        return '@' + a.username
    return a.phone or str(a.telegram_user_id or a.id)


class AiGroupService:
    """炒群任务(按群)管理:群 → 成员(账号 + 独立人设)→ 剧本;私信自动回复按账号。"""

    @staticmethod
    async def _check_scope(db: AsyncSession, request: Request, tenant_id: int, project_id: int) -> None:
        if request.user.is_superuser:
            return
        if not await membership_dao.get_by_scope(db, tenant_id, project_id, request.user.id):
            raise errors.ForbiddenError(msg='无该项目权限')

    @staticmethod
    async def _scopes(db: AsyncSession, request: Request) -> set[tuple[int, int]] | None:
        if request.user.is_superuser:
            return None
        return {(m.tenant_id, m.project_id) for m in await membership_dao.get_all(db, user_id=request.user.id)}

    @staticmethod
    async def get_group(db: AsyncSession, request: Request, pk: int) -> TgAiGroup:
        group = await ai_group_dao.get(db, pk)
        if group is None:
            raise errors.NotFoundError(msg='炒群任务不存在')
        await AiGroupService._check_scope(db, request, group.tenant_id, group.project_id)
        return group

    @staticmethod
    async def _members(db: AsyncSession, group: TgAiGroup) -> list[TgAiBinding]:
        rows = await ai_binding_dao.get_all(db, tenant_id=group.tenant_id, project_id=group.project_id)
        return [b for b in rows if b.group_id == group.id]

    @staticmethod
    async def _detail(db: AsyncSession, group: TgAiGroup) -> GetAiGroupDetail:
        members = await AiGroupService._members(db, group)
        ids = [b.id for b in members] or [0]
        day_start = timezone.now().replace(hour=16, minute=0, second=0, microsecond=0)
        if day_start > timezone.now():
            day_start -= timedelta(days=1)
        today = (
            await db.execute(
                sa
                .select(sa.func.count())
                .select_from(TgAiRun)
                .join(TgAiConversation, TgAiConversation.id == TgAiRun.conversation_id)
                .where(
                    TgAiConversation.binding_id.in_(ids),
                    TgAiRun.status == 'completed',
                    TgAiRun.created_time >= day_start,
                )
            )
        ).scalar() or 0
        pending = (
            await db.execute(
                sa
                .select(sa.func.count())
                .select_from(TgReplyCandidate)
                .where(
                    TgReplyCandidate.tenant_id == group.tenant_id,
                    TgReplyCandidate.target_chat_id == group.chat_id,
                    TgReplyCandidate.account_id.in_([b.account_id for b in members] or [0]),
                    TgReplyCandidate.status == 'pending',
                    TgReplyCandidate.deleted == 0,
                )
            )
        ).scalar() or 0
        d = GetAiGroupDetail.model_validate(group)
        d.member_count = len(members)
        d.active_member_count = sum(1 for b in members if b.status == 'active')
        d.today_replies = today
        d.pending_approvals = pending
        return d

    @staticmethod
    async def list_groups(
        *, db: AsyncSession, request: Request, tenant_id: int | None, project_id: int | None
    ) -> list[GetAiGroupDetail]:
        scopes = await AiGroupService._scopes(db, request)
        groups = [
            g
            for g in await ai_group_dao.get_all(db, tenant_id=tenant_id, project_id=project_id)
            if scopes is None or (g.tenant_id, g.project_id) in scopes
        ]
        return [await AiGroupService._detail(db, g) for g in sorted(groups, key=lambda g: g.id)]

    @staticmethod
    def _group_fields(obj: CreateAiGroupParam | UpdateAiGroupParam) -> dict:
        fields = obj.model_dump(exclude_unset=True, exclude={'provider_key', 'chat', 'join_account_id'})
        if obj.provider_key:
            fields['provider_key_enc'] = _provider_cipher().encrypt(obj.provider_key)
        if 'blocked_words' in fields and fields['blocked_words'] is not None:
            fields['blocked_words'] = [w.strip() for w in fields['blocked_words'] if w and w.strip()]
        return {k: v for k, v in fields.items() if v is not None or k in {'theme', 'remark', 'provider_model'}}

    @staticmethod
    async def _resolve_chat(
        db: AsyncSession, tenant_id: int, project_id: int, chat: str, account_id: int | None
    ) -> tuple[int, str | None]:
        ref = chat.strip()
        if ref.lstrip('-').isdigit() and account_id is None:
            return int(ref), None
        if account_id is None:
            raise errors.RequestError(msg='填链接时需要选一个成员账号用于解析/进群')
        account = await telegram_account_dao.get_by_scope(db, tenant_id, project_id, account_id)
        if account is None:
            raise errors.NotFoundError(msg='账号不存在')
        r = (await join_chat_refs(account, [ref])).get(ref)
        if not r or not r.get('ok'):
            status = ((r or {}).get('error') or {}).get('status', 'resolve_failed')
            raise errors.RequestError(msg=f'群 {ref}: {JOIN_ERR.get(status, "进群/解析失败")}')
        return int(r['chat_id']), None if ref.lstrip('-').isdigit() else ref

    @staticmethod
    async def create_group(*, db: AsyncSession, request: Request, obj: CreateAiGroupParam) -> GetAiGroupDetail:
        await AiGroupService._check_scope(db, request, obj.tenant_id, obj.project_id)
        chat_id, chat_ref = await AiGroupService._resolve_chat(
            db, obj.tenant_id, obj.project_id, obj.chat, obj.join_account_id
        )
        exists = await ai_group_dao.get_all(db, tenant_id=obj.tenant_id, project_id=obj.project_id)
        if any(g.chat_id == chat_id and (g.topic_id or None) == (obj.topic_id or None) for g in exists):
            raise errors.ConflictError(msg='该群(话题)已有炒群任务')
        fields = AiGroupService._group_fields(obj)
        for k in ('tenant_id', 'project_id', 'name', 'topic_id'):
            fields.pop(k, None)
        group = TgAiGroup(
            tenant_id=obj.tenant_id,
            project_id=obj.project_id,
            name=obj.name,
            chat_id=chat_id,
            chat_ref=chat_ref,
            topic_id=obj.topic_id,
            **fields,
        )
        db.add(group)
        await db.flush()
        return await AiGroupService._detail(db, group)

    @staticmethod
    async def update_group(*, db: AsyncSession, request: Request, pk: int, obj: UpdateAiGroupParam) -> GetAiGroupDetail:
        group = await AiGroupService.get_group(db, request, pk)
        merged_min = obj.reply_min if obj.reply_min is not None else group.reply_min
        merged_max = obj.reply_max if obj.reply_max is not None else group.reply_max
        if merged_max < merged_min:
            raise errors.RequestError(msg='最多接话号数不能小于最少接话号数')
        fields = AiGroupService._group_fields(obj)
        if fields:
            await ai_group_dao.update_model(db, pk, fields)
        await db.refresh(group)
        return await AiGroupService._detail(db, group)

    @staticmethod
    async def delete_group(*, db: AsyncSession, request: Request, pk: int) -> None:
        group = await AiGroupService.get_group(db, request, pk)
        for b in await AiGroupService._members(db, group):
            await ai_binding_dao.delete(db, b.id)
        for s in await ai_script_dao.get_all(db, group_id=group.id):
            await ai_script_dao.delete_model(db, s.id)
        await ai_group_dao.delete_model(db, pk)

    @staticmethod
    async def list_members(*, db: AsyncSession, request: Request, pk: int) -> list[GetAiMemberDetail]:
        group = await AiGroupService.get_group(db, request, pk)
        members = await AiGroupService._members(db, group)
        accounts = {
            a.id: a
            for a in (
                await db.execute(
                    sa.select(TgTelegramAccount).where(TgTelegramAccount.id.in_([b.account_id for b in members] or [0]))
                )
            ).scalars()
        }
        out = []
        for b in sorted(members, key=lambda b: b.id):
            acc = accounts.get(b.account_id)
            out.append(
                GetAiMemberDetail(
                    id=b.id,
                    group_id=b.group_id,
                    account_id=b.account_id,
                    role_name=b.role_name,
                    persona=b.persona,
                    talkativeness=b.random_prob,
                    reply_delay_s=b.reply_delay_s,
                    provider_model=b.provider_model,
                    base_url=b.base_url,
                    has_provider_key=bool(b.provider_key_enc),
                    status=b.status,
                    account_label=_account_label(acc),
                    account_running=bool(acc and acc.desired_status == 'running' and not acc.deleted),
                )
            )
        return out

    @staticmethod
    def _member_fields(obj: AiMemberParam) -> dict:
        fields = obj.model_dump(exclude_unset=True, exclude={'provider_key', 'talkativeness', 'account_id'})
        if obj.talkativeness is not None:
            fields['random_prob'] = obj.talkativeness
            fields['speak_policy'] = 'random'
        if obj.provider_key:
            fields['provider_key_enc'] = _provider_cipher().encrypt(obj.provider_key)
        return fields

    @staticmethod
    async def add_member(*, db: AsyncSession, request: Request, pk: int, obj: AiMemberParam) -> None:
        group = await AiGroupService.get_group(db, request, pk)
        if obj.account_id is None:
            raise errors.RequestError(msg='请选择账号')
        account = await telegram_account_dao.get_by_scope(db, group.tenant_id, group.project_id, obj.account_id)
        if account is None:
            raise errors.NotFoundError(msg='账号不存在')
        if any(b.account_id == obj.account_id for b in await AiGroupService._members(db, group)):
            raise errors.ConflictError(msg='该账号已是本群成员')
        if group.chat_ref:
            r = (await join_chat_refs(account, [group.chat_ref])).get(group.chat_ref)
            if not r or not r.get('ok'):
                status = ((r or {}).get('error') or {}).get('status', 'resolve_failed')
                raise errors.RequestError(msg=f'账号进群失败:{JOIN_ERR.get(status, "进群/解析失败")}')
        fields = {'speak_policy': 'random', 'random_prob': 30, 'status': 'active', 'base_url': ''}
        fields |= AiGroupService._member_fields(obj)
        binding = TgAiBinding(
            tenant_id=group.tenant_id,
            project_id=group.project_id,
            account_id=obj.account_id,
            engine='openai',
            chat_id=group.chat_id,
            topic_id=group.topic_id,
            group_id=group.id,
            bot_uuid='',
            inbound_secret_ref='',
            outbound_secret_ref='',
            **fields,
        )
        db.add(binding)
        await db.flush()

    @staticmethod
    async def _member(db: AsyncSession, request: Request, pk: int, member_id: int) -> TgAiBinding:
        group = await AiGroupService.get_group(db, request, pk)
        b = await ai_binding_dao.get(db, member_id)
        if b is None or b.group_id != group.id:
            raise errors.NotFoundError(msg='成员不存在')
        return b

    @staticmethod
    async def update_member(*, db: AsyncSession, request: Request, pk: int, member_id: int, obj: AiMemberParam) -> None:
        await AiGroupService._member(db, request, pk, member_id)
        fields = AiGroupService._member_fields(obj)
        if fields:
            await ai_binding_dao.update_fields(db, member_id, fields)

    @staticmethod
    async def delete_member(*, db: AsyncSession, request: Request, pk: int, member_id: int) -> None:
        await AiGroupService._member(db, request, pk, member_id)
        await ai_binding_dao.delete(db, member_id)

    @staticmethod
    async def group_runs(*, db: AsyncSession, request: Request, pk: int, limit: int = 100) -> list[GetAiGroupRunDetail]:
        """发言记录:本群成员最近的生成,含触发消息、产出内容、审批/投递状态与失败/跳过原因。"""
        group = await AiGroupService.get_group(db, request, pk)
        members = {b.id: b for b in await AiGroupService._members(db, group)}
        rows = (
            await db.execute(
                sa
                .select(TgAiRun, TgAiConversation.binding_id, TgReplyCandidate)
                .join(TgAiConversation, TgAiConversation.id == TgAiRun.conversation_id)
                .outerjoin(TgReplyCandidate, TgReplyCandidate.id == TgAiRun.candidate_id)
                .where(TgAiConversation.binding_id.in_(list(members) or [0]), TgAiRun.deleted == 0)
                .order_by(TgAiRun.id.desc())
                .limit(limit)
            )
        ).all()
        accounts = {
            a.id: a
            for a in (
                await db.execute(
                    sa.select(TgTelegramAccount).where(
                        TgTelegramAccount.id.in_([b.account_id for b in members.values()] or [0])
                    )
                )
            ).scalars()
        }
        out = []
        for run, binding_id, cand in rows:
            b = members.get(binding_id)
            src = run.trigger_source or {}
            out.append(
                GetAiGroupRunDetail(
                    id=run.id,
                    created_time=run.created_time,
                    status=run.status,
                    mode=src.get('mode', 'reply'),
                    member_id=binding_id,
                    role_name=b.role_name if b else None,
                    account_label=_account_label(accounts.get(b.account_id) if b else None),
                    trigger_text=str(src.get('script_line') or src.get('text') or '')[:300],
                    trigger_sender=src.get('sender_name'),
                    content=cand.content if cand else None,
                    candidate_status=cand.status if cand else None,
                    last_error=run.last_error,
                    model=(run.usage or {}).get('model'),
                )
            )
        return out

    @staticmethod
    async def warmup_now(*, db: AsyncSession, request: Request, pk: int) -> bool:
        group = await AiGroupService.get_group(db, request, pk)
        if group.status != 'active':
            raise errors.RequestError(msg='任务未运行,先启动再暖场')
        return await AiService.warmup_group(db, group, now=timezone.now(), force=True)

    # ---- 人设模板 ----
    @staticmethod
    async def list_personas(
        *, db: AsyncSession, request: Request, tenant_id: int | None, project_id: int | None
    ) -> list[TgAiPersona]:
        scopes = await AiGroupService._scopes(db, request)
        return [
            p
            for p in await ai_persona_dao.get_all(db, tenant_id=tenant_id, project_id=project_id)
            if scopes is None or (p.tenant_id, p.project_id) in scopes
        ]

    @staticmethod
    async def save_persona(
        *, db: AsyncSession, request: Request, obj: AiPersonaParam, pk: int | None = None
    ) -> TgAiPersona:
        await AiGroupService._check_scope(db, request, obj.tenant_id, obj.project_id)
        if pk is None:
            p = TgAiPersona(**obj.model_dump())
            db.add(p)
            await db.flush()
            return p
        p = await ai_persona_dao.get(db, pk)
        if p is None or (p.tenant_id, p.project_id) != (obj.tenant_id, obj.project_id):
            raise errors.NotFoundError(msg='人设模板不存在')
        await ai_persona_dao.update_model(db, pk, obj.model_dump())
        await db.refresh(p)
        return p

    @staticmethod
    async def delete_persona(*, db: AsyncSession, request: Request, pk: int) -> None:
        p = await ai_persona_dao.get(db, pk)
        if p is None:
            raise errors.NotFoundError(msg='人设模板不存在')
        await AiGroupService._check_scope(db, request, p.tenant_id, p.project_id)
        await ai_persona_dao.delete_model(db, pk)

    # ---- 剧本 ----
    @staticmethod
    async def list_scripts(*, db: AsyncSession, request: Request, pk: int) -> list[TgAiScript]:
        group = await AiGroupService.get_group(db, request, pk)
        return sorted(await ai_script_dao.get_all(db, group_id=group.id), key=lambda s: s.id)

    @staticmethod
    async def _check_lines(db: AsyncSession, group: TgAiGroup, obj: AiScriptParam) -> list[dict]:
        ids = {b.id for b in await AiGroupService._members(db, group)}
        bad = [ln.member_id for ln in obj.lines if ln.member_id not in ids]
        if bad:
            raise errors.RequestError(msg='剧本里有不属于本群的成员')
        return [ln.model_dump() for ln in obj.lines]

    @staticmethod
    async def save_script(
        *, db: AsyncSession, request: Request, pk: int, obj: AiScriptParam, script_id: int | None = None
    ) -> TgAiScript:
        group = await AiGroupService.get_group(db, request, pk)
        lines = await AiGroupService._check_lines(db, group, obj)
        if script_id is None:
            s = TgAiScript(
                tenant_id=group.tenant_id,
                project_id=group.project_id,
                group_id=group.id,
                name=obj.name,
                lines=lines,
                interval_s=obj.interval_s,
                rewrite=obj.rewrite,
            )
            db.add(s)
            await db.flush()
            return s
        s = await AiGroupService._script(db, group, script_id)
        if s.status == 'running':
            raise errors.RequestError(msg='剧本正在播放,先停止再修改')
        await ai_script_dao.update_model(
            db, s.id, {'name': obj.name, 'lines': lines, 'interval_s': obj.interval_s, 'rewrite': obj.rewrite}
        )
        await db.refresh(s)
        return s

    @staticmethod
    async def _script(db: AsyncSession, group: TgAiGroup, script_id: int) -> TgAiScript:
        s = await ai_script_dao.get(db, script_id)
        if s is None or s.group_id != group.id:
            raise errors.NotFoundError(msg='剧本不存在')
        return s

    @staticmethod
    async def delete_script(*, db: AsyncSession, request: Request, pk: int, script_id: int) -> None:
        group = await AiGroupService.get_group(db, request, pk)
        s = await AiGroupService._script(db, group, script_id)
        await ai_script_dao.delete_model(db, s.id)

    @staticmethod
    async def start_script(*, db: AsyncSession, request: Request, pk: int, script_id: int) -> str:
        """开始播放:新令牌 + cursor 归零;旧令牌的排队步骤会自然失效。"""
        group = await AiGroupService.get_group(db, request, pk)
        if group.status != 'active':
            raise errors.RequestError(msg='任务未运行,先启动再播放剧本')
        s = await AiGroupService._script(db, group, script_id)
        token = uuid4_str()
        await ai_script_dao.update_model(db, s.id, {'status': 'running', 'run_token': token, 'cursor': 0})
        return token

    @staticmethod
    async def stop_script(*, db: AsyncSession, request: Request, pk: int, script_id: int) -> None:
        group = await AiGroupService.get_group(db, request, pk)
        s = await AiGroupService._script(db, group, script_id)
        await ai_script_dao.update_model(db, s.id, {'status': 'idle', 'run_token': None})

    # ---- 私信自动回复 ----
    @staticmethod
    async def list_private(
        *, db: AsyncSession, request: Request, tenant_id: int | None, project_id: int | None
    ) -> list[TgAiPrivateReply]:
        scopes = await AiGroupService._scopes(db, request)
        return [
            p
            for p in await ai_private_reply_dao.get_all(db, tenant_id=tenant_id, project_id=project_id)
            if scopes is None or (p.tenant_id, p.project_id) in scopes
        ]

    @staticmethod
    async def save_private(
        *, db: AsyncSession, request: Request, account_id: int, obj: AiPrivateReplyParam
    ) -> TgAiPrivateReply:
        account = await telegram_account_dao.get(db, account_id)
        if account is None:
            raise errors.NotFoundError(msg='账号不存在')
        await AiGroupService._check_scope(db, request, account.tenant_id, account.project_id)
        cur = next(iter(await ai_private_reply_dao.get_all(db, account_id=account_id)), None)
        if cur is None:
            cur = TgAiPrivateReply(
                tenant_id=account.tenant_id, project_id=account.project_id, account_id=account_id, **obj.model_dump()
            )
            db.add(cur)
            await db.flush()
            return cur
        await ai_private_reply_dao.update_model(db, cur.id, obj.model_dump())
        await db.refresh(cur)
        return cur


ai_group_service: AiGroupService = AiGroupService()

import asyncio

from datetime import timedelta
from itertools import starmap

import sqlalchemy as sa

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tg.crud.crud_clone_rule import (
    clone_rule_dao,
    clone_rule_version_dao,
    clone_target_dao,
)
from backend.app.tg.crud.crud_membership import membership_dao
from backend.app.tg.crud.crud_project import project_dao
from backend.app.tg.crud.crud_runtime_command import runtime_command_dao
from backend.app.tg.crud.crud_telegram_account import telegram_account_dao
from backend.app.tg.model import TgCloneRule, TgCloneRuleVersion, TgCloneTarget, TgDeliveryJob, TgTelegramAccount
from backend.app.tg.schema.clone_rule import (
    CloneTargetParam,
    CreateCloneRuleParam,
    CreateCloneRuleVersionParam,
    CreateCloneTargetParam,
    UpdateCloneRuleParam,
)
from backend.app.tg.schema.runtime_command import CreateRuntimeCommandInternalParam, CreateRuntimeCommandParam
from backend.app.tg.service.account_service import (
    JOIN_ERR,
    check_chat_membership,
    join_chat_refs,
    resolve_user_refs,
)
from backend.app.tg.service.command_service import runtime_command_service
from backend.common.exception import errors
from backend.database.db import uuid4_str
from backend.utils.timezone import timezone


def _snapshot(rule: TgCloneRule, targets: list) -> dict:
    return {
        'rule': {
            'id': rule.id,
            'uuid': rule.uuid,
            'name': rule.name,
            'account_id': rule.account_id,
            'sender_account_ids': CloneRuleService._sender_pool(rule),
            # 变形闸开关只告诉 worker "要不要调 clone_transform";具体配置由控制面按 rule_id 实时读取
            'transform': (rule.ai_rewrite or 'off') != 'off' or (rule.ad_block or 'off') != 'off',
            'mode': rule.mode,
            'sync_edit': rule.sync_edit,
            'sync_delete': rule.sync_delete,
            'enabled': rule.enabled,
            'delay_min_s': rule.delay_min_s,
            'delay_max_s': rule.delay_max_s,
        },
        'targets': [
            {
                'route_id': t.route_id,
                'source_chat_id': t.source_chat_id,
                'source_topic_id': t.source_topic_id,
                'target_chat_id': t.target_chat_id,
                'target_topic_id': t.target_topic_id,
                'filters': t.filters,
            }
            for t in targets
        ],
    }


_SENDER_KEYS = ('sender_user_ids', 'blocked_sender_ids')
_TERMINAL = ('succeeded', 'reconciled_succeeded', 'blocked', 'failed_permanent')
TARGET_LOST = '目标群发不了消息(账号可能被移出/禁言/群已解散)'
SOURCE_LOST = '账号已不在源群,收不到消息'
DEST_LOST = '账号已不在目标群'


async def route_health(db: AsyncSession, targets: list[TgCloneTarget]) -> dict[int, str | None]:
    """路线健康:检测记录的失效原因优先;否则看该路线最近一次投递结果是否为无权限(进群之后的)。"""
    health: dict[int, str | None] = {t.id: t.health_reason for t in targets}
    route_ids = [t.route_id for t in targets if not t.health_reason]
    if not route_ids:
        return health
    ranked = (
        sa
        .select(
            TgDeliveryJob.route_id,
            TgDeliveryJob.status,
            TgDeliveryJob.last_error_class,
            TgDeliveryJob.updated_at,
            sa.func
            .row_number()
            .over(partition_by=TgDeliveryJob.route_id, order_by=TgDeliveryJob.updated_at.desc())
            .label('rn'),
        )
        .where(TgDeliveryJob.route_id.in_(route_ids), TgDeliveryJob.status.in_(_TERMINAL))
        .subquery()
    )
    rows = (await db.execute(sa.select(ranked).where(ranked.c.rn == 1))).all()
    latest = {r.route_id: r for r in rows}
    for t in targets:
        r = latest.get(t.route_id)
        if not r or t.health_reason:
            continue
        lost = r.status == 'blocked' or r.last_error_class == 'permission'
        if lost and (t.joined_at is None or r.updated_at is None or r.updated_at > t.joined_at):
            health[t.id] = TARGET_LOST
    return health


def _route_key(t: TgCloneTarget) -> tuple:
    return (t.source_chat_id, t.source_topic_id, t.target_chat_id, t.target_topic_id)


class CloneRuleService:
    """Clone 规则服务类(§6.2/§7.1:发布产生不可变快照)"""

    @staticmethod
    def _sender_pool(rule: TgCloneRule) -> list[int]:
        """发送号池(去重保序):空池回退为仅监听号发送,兼容存量规则。"""
        pool = [int(a) for a in (rule.sender_account_ids or []) if a]
        return list(dict.fromkeys(pool)) or [rule.account_id]

    @staticmethod
    async def _validate_pool(db: AsyncSession, tenant_id: int, project_id: int, pool: list[int], mode: str) -> None:
        """池内账号必须属于该项目;多号池只支持 copy(forward 需要发送号在源群)。"""
        if pool and mode != 'copy':
            raise errors.RequestError(msg='多号搬运只支持 copy 模式')
        for acc_id in dict.fromkeys(pool):
            if not await telegram_account_dao.get_by_scope(db, tenant_id, project_id, acc_id):
                raise errors.NotFoundError(msg=f'发送账号 {acc_id} 不存在于该项目')

    @staticmethod
    async def _check_scope(db: AsyncSession, request: Request, tenant_id: int, project_id: int) -> None:
        if request.user.is_superuser:
            return
        if not await membership_dao.get_by_scope(db, tenant_id, project_id, request.user.id):
            raise errors.ForbiddenError(msg='无该项目权限')

    @staticmethod
    async def get(*, db: AsyncSession, request: Request, pk: int) -> TgCloneRule:
        rule = await clone_rule_dao.get(db, pk)
        if not rule:
            raise errors.NotFoundError(msg='规则不存在')
        await CloneRuleService._check_scope(db, request, rule.tenant_id, rule.project_id)
        return rule

    @staticmethod
    async def get_with_targets(db: AsyncSession, request: Request, pk: int) -> TgCloneRule:
        rule = await CloneRuleService.get(db=db, request=request, pk=pk)
        targets = list(await clone_target_dao.get_all_by_rule(db, rule.id))
        health = await route_health(db, [t for t in targets if t.status == 'active'])
        for t in targets:
            t.health = health.get(t.id)
        rule.targets = targets
        return rule

    @staticmethod
    async def get_all(
        *, db: AsyncSession, request: Request, tenant_id: int | None = None, project_id: int | None = None
    ) -> list[TgCloneRule]:
        rules = list(await clone_rule_dao.get_all(db, tenant_id, project_id))
        if request.user.is_superuser:
            return rules
        memberships = await membership_dao.get_all(db, user_id=request.user.id)
        scopes = {(m.tenant_id, m.project_id) for m in memberships}
        return [r for r in rules if (r.tenant_id, r.project_id) in scopes]

    @staticmethod
    async def create(*, db: AsyncSession, request: Request, obj: CreateCloneRuleParam) -> None:
        await CloneRuleService._check_scope(db, request, obj.tenant_id, obj.project_id)
        project = await project_dao.get(db, obj.project_id)
        if not project or project.tenant_id != obj.tenant_id:
            raise errors.NotFoundError(msg='项目不存在')
        account = await telegram_account_dao.get_by_scope(db, obj.tenant_id, obj.project_id, obj.account_id)
        if not account:
            raise errors.NotFoundError(msg='账号不存在于该项目')
        await CloneRuleService._validate_pool(db, obj.tenant_id, obj.project_id, obj.sender_account_ids, obj.mode)
        await clone_rule_dao.create(db, obj)

    @staticmethod
    async def _notify_reload(db: AsyncSession, request: Request, rule: TgCloneRule) -> None:
        """规则停用/发布/删除后让 worker 重拉快照,并拦截已停用规则的残留队列。"""
        await runtime_command_service.issue(
            db=db,
            request=request,
            account_id=rule.account_id,
            obj=CreateRuntimeCommandParam(type='ReloadConfig', dedup_key=f'reloadcfg-{uuid4_str()}'),
        )

    _LISTENER_DEAD = {'auth_dead', 'revoked', 'banned', 'frozen', 'error', 'disabled', 'reauth_required'}

    @staticmethod
    async def failover_listener_if_dead(  # ruff: ignore[complex-structure]
        *, db: AsyncSession, account: TgTelegramAccount, status: str
    ) -> int | None:
        """监听号死亡→从发送号池挑一个健康号接管监听并通知重载(§12 自愈)。
        候选必须期望运行中、观测状态非死态且有会话;接管前先用源群原始链接
        让新号进群(发送号只在目标群,不在源群)。返回新监听账号 id。"""
        if status not in CloneRuleService._LISTENER_DEAD:
            return None
        rules = await clone_rule_dao.get_all(db)
        new_id: int | None = None
        for rule in rules:
            if rule.account_id != account.id or rule.status != 'published' or not rule.enabled:
                continue
            targets = await clone_target_dao.get_all_by_rule(db, rule.id)
            src_refs = [t.source_chat_ref for t in targets if t.status == 'active' and t.source_chat_ref]
            cand = None
            for pid in [int(x) for x in (rule.sender_account_ids or [])]:
                if pid == account.id:
                    continue
                a = await telegram_account_dao.get_by_scope(db, rule.tenant_id, rule.project_id, pid)
                if not (
                    a
                    and a.desired_status == 'running'
                    and a.observed_status not in CloneRuleService._LISTENER_DEAD
                    and a.secret_ref
                ):
                    continue
                if src_refs:
                    try:
                        results = await join_chat_refs(a, src_refs)
                    except Exception:
                        continue
                    if not all((results.get(r) or {}).get('ok') for r in src_refs):
                        continue
                cand = a
                break
            if cand is None:
                continue
            await clone_rule_dao.update(db, rule.id, {'account_id': cand.id})
            await runtime_command_dao.create(
                db,
                CreateRuntimeCommandInternalParam(
                    tenant_id=rule.tenant_id,
                    project_id=rule.project_id,
                    account_id=cand.id,
                    type='ReloadConfig',
                    dedup_key=f'failover-{rule.id}-{uuid4_str()[:8]}',
                    issued_by=0,
                    deadline=timezone.now() + timedelta(minutes=30),
                ),
            )
            new_id = cand.id
        return new_id

    @staticmethod
    async def update(*, db: AsyncSession, request: Request, pk: int, obj: UpdateCloneRuleParam) -> int:
        rule = await CloneRuleService.get(db=db, request=request, pk=pk)
        data = {k: v for k, v in obj.model_dump().items() if v is not None}
        if 'sender_account_ids' in data or 'mode' in data:
            pool = data.get('sender_account_ids', rule.sender_account_ids or [])
            mode = data.get('mode', rule.mode)
            await CloneRuleService._validate_pool(db, rule.tenant_id, rule.project_id, pool, mode)
        # 停用优先于快照:enabled=False 立即生效,不依赖下次发布
        updated = await clone_rule_dao.update(db, pk, data)
        await CloneRuleService._notify_reload(db, request, rule)
        return updated

    @staticmethod
    def _chat_ref(value: int | str) -> str:
        return str(value).strip()

    @staticmethod
    async def _resolve_refs(db: AsyncSession, rule: TgCloneRule, refs: list[str | int]) -> dict[str, dict]:
        """用规则账号的会话解析/加入群标识,返回 {ref: {ok,chat_id,title,status|error}}"""
        account = await telegram_account_dao.get(db, rule.account_id)
        if not account:
            raise errors.NotFoundError(msg='规则所属账号不存在')
        return await join_chat_refs(account, refs)

    @staticmethod
    def _resolve_or_raise(results: dict[str, dict], ref: str, label: str) -> int:
        r = results.get(ref)
        if not r or not r.get('ok'):
            status = ((r or {}).get('error') or {}).get('status', 'resolve_failed')
            raise errors.RequestError(msg=f'{label} {ref}: {JOIN_ERR.get(status, "进群/解析失败")}')
        return int(r['chat_id'])

    @staticmethod
    async def _normalize_filters(  # ruff: ignore[complex-structure]
        db: AsyncSession, rule: TgCloneRule, filters: dict | None
    ) -> dict | None:
        """发言人过滤里的 @username 解析为用户 ID;原始写法存到 `<key>_refs` 供编辑回显。"""
        if not filters:
            return filters
        out = dict(filters)
        pending: dict[str, list[str]] = {}
        for key in _SENDER_KEYS:
            tokens = [str(x).strip() for x in (filters.get(key) or []) if str(x).strip()]
            out.pop(f'{key}_refs', None)
            if not tokens:
                out.pop(key, None)
                continue
            pending[key] = tokens
        names = [t for tokens in pending.values() for t in tokens if not t.isdigit()]
        resolved: dict[str, dict] = {}
        if names:
            account = await telegram_account_dao.get(db, rule.account_id)
            if not account:
                raise errors.NotFoundError(msg='规则所属账号不存在')
            resolved = await resolve_user_refs(account, list(dict.fromkeys(names)))
        for key, tokens in pending.items():
            ids: list[int] = []
            for tok in tokens:
                if tok.isdigit():
                    ids.append(int(tok))
                    continue
                r = resolved.get(tok) or {}
                if not r.get('ok'):
                    raise errors.RequestError(msg=f'发言人 {tok} 找不到,请检查用户名')
                ids.append(int(r['user_id']))
            out[key] = list(dict.fromkeys(ids))
            if any(not t.isdigit() for t in tokens):
                out[f'{key}_refs'] = tokens
        return out

    @staticmethod
    async def add_target(*, db: AsyncSession, request: Request, rule_id: int, obj: CloneTargetParam) -> TgCloneTarget:
        rule = await CloneRuleService.get(db=db, request=request, pk=rule_id)
        if rule.status == 'disabled':
            raise errors.RequestError(msg='规则已停用')
        src_ref, dst_ref = (
            CloneRuleService._chat_ref(obj.source_chat_id),
            CloneRuleService._chat_ref(obj.target_chat_id),
        )
        if not src_ref or not dst_ref:
            raise errors.RequestError(msg='源群/目标群必填')
        results = await CloneRuleService._resolve_refs(db, rule, [src_ref, dst_ref])
        src_id = CloneRuleService._resolve_or_raise(results, src_ref, '源群')
        dst_id = CloneRuleService._resolve_or_raise(results, dst_ref, '目标群')
        if src_id == dst_id and obj.source_topic_id == obj.target_topic_id:
            raise errors.RequestError(msg='禁止源=目标的自环')
        filters = await CloneRuleService._normalize_filters(db, rule, obj.filters)
        route = (src_id, obj.source_topic_id, dst_id, obj.target_topic_id)
        for t in await clone_target_dao.get_active_by_rule(db, rule.id):
            if _route_key(t) == route:
                raise errors.RequestError(msg='该规则已有相同的源群→目标群路线,不能重复添加')
        return await clone_target_dao.create(
            db,
            CreateCloneTargetParam(
                rule_id=rule_id,
                tenant_id=rule.tenant_id,
                project_id=rule.project_id,
                source_chat_id=src_id,
                source_chat_ref=src_ref,
                source_topic_id=obj.source_topic_id,
                target_chat_id=dst_id,
                target_chat_ref=dst_ref,
                target_topic_id=obj.target_topic_id,
                joined_account_id=rule.account_id,
                filters=filters,
                remark=obj.remark,
            ),
        )

    @staticmethod
    async def _auto_join(db: AsyncSession, rule: TgCloneRule, targets: list[TgCloneTarget]) -> None:
        """运行前让规则账号自动加入/验证尚未由该账号进过的群(链接可进群,纯 ID 仅验证)。"""
        health = await route_health(db, targets)
        extra_senders = [a for a in CloneRuleService._sender_pool(rule) if a != rule.account_id]
        listener_targets = [t for t in targets if t.joined_account_id != rule.account_id or health.get(t.id)]
        sender_targets = [t for t in targets if any(a not in (t.joined_account_ids or []) for a in extra_senders)]
        if not listener_targets and not sender_targets:
            return
        # 监听号:进源群+目标群(收消息+回取原文)
        if listener_targets:
            uniq = list(
                dict.fromkeys(
                    r
                    for t in listener_targets
                    for r in (t.source_chat_ref or str(t.source_chat_id), t.target_chat_ref or str(t.target_chat_id))
                )
            )
            results = await CloneRuleService._resolve_refs(db, rule, uniq)
            for t in listener_targets:
                for attr_ref, attr_id, label in (
                    ('source_chat_ref', 'source_chat_id', '源群'),
                    ('target_chat_ref', 'target_chat_id', '目标群'),
                ):
                    ref = getattr(t, attr_ref) or str(getattr(t, attr_id))
                    chat_id = CloneRuleService._resolve_or_raise(results, ref, label)
                    if getattr(t, attr_id) != chat_id:
                        setattr(t, attr_id, chat_id)
                t.joined_account_id = rule.account_id
                t.joined_at = timezone.now()
                t.health_reason = None
                db.add(t)
        # 发送号池:只进目标群,逐号串行进群
        await CloneRuleService._auto_join_pool(db, extra_senders, targets)
        await db.flush()

    @staticmethod
    async def _auto_join_pool(db: AsyncSession, extra_senders: list[int], targets: list[TgCloneTarget]) -> None:
        for acc_id in extra_senders:
            need = [t for t in targets if acc_id not in (t.joined_account_ids or [])]
            if not need:
                continue
            account = await telegram_account_dao.get(db, acc_id)
            if not account:
                raise errors.NotFoundError(msg=f'发送账号 {acc_id} 不存在')
            uniq = list(dict.fromkeys(t.target_chat_ref or str(t.target_chat_id) for t in need))
            results = await join_chat_refs(account, uniq)
            for t in need:
                ref = t.target_chat_ref or str(t.target_chat_id)
                chat_id = CloneRuleService._resolve_or_raise(results, ref, '目标群')
                if t.target_chat_id != chat_id:
                    t.target_chat_id = chat_id
                ids = list(t.joined_account_ids or [])
                if acc_id not in ids:
                    ids.append(acc_id)
                t.joined_account_ids = ids
                sender_status = dict(t.sender_status or {})
                sender_status[str(acc_id)] = {
                    'status': 'member',
                    'can_post': None,
                    'checked_at': timezone.now().isoformat(),
                }
                t.sender_status = sender_status
                db.add(t)

    @staticmethod
    async def mark_chat_lost(*, db: AsyncSession, account_id: int, chat_id: int, reason: str) -> int:
        """账号已不在该群:相关路线标失效并清进群记录,下次运行用链接重新进群。"""
        rule_ids = (
            (
                await db.execute(
                    sa.select(TgCloneRule.id).where(TgCloneRule.account_id == account_id, TgCloneRule.deleted == 0)
                )
            )
            .scalars()
            .all()
        )
        if not rule_ids:
            return 0
        targets = (
            (
                await db.execute(
                    sa.select(TgCloneTarget).where(
                        TgCloneTarget.rule_id.in_(rule_ids),
                        TgCloneTarget.status == 'active',
                        TgCloneTarget.deleted == 0,
                        sa.or_(TgCloneTarget.source_chat_id == chat_id, TgCloneTarget.target_chat_id == chat_id),
                    )
                )
            )
            .scalars()
            .all()
        )
        suffix = '(被移出或群已不可见)' if reason == 'kicked' else ''
        for t in targets:
            t.health_reason = (SOURCE_LOST if t.source_chat_id == chat_id else DEST_LOST) + suffix
            if t.joined_account_id == account_id:
                t.joined_account_id = None
            t.joined_account_ids = [a for a in (t.joined_account_ids or []) if a != account_id]
            db.add(t)
        await db.flush()
        return len(targets)

    @staticmethod
    async def check_routes(*, db: AsyncSession, request: Request, pk: int) -> list[dict]:
        """实时检测规则账号是否仍在每条路线的源群/目标群里(只验证不进群);不在则标失效并清进群记录。"""
        rule = await CloneRuleService.get(db=db, request=request, pk=pk)
        targets = list(await clone_target_dao.get_active_by_rule(db, rule.id))
        if not targets:
            return []
        ids = list(dict.fromkeys(str(x) for t in targets for x in (t.source_chat_id, t.target_chat_id)))
        results = await CloneRuleService._resolve_refs(db, rule, ids)
        sender_accounts, sender_results = await CloneRuleService._check_pool_membership(db, rule, targets)
        checked_at = timezone.now().isoformat()
        out = []
        for t in targets:
            src_ok = (results.get(str(t.source_chat_id)) or {}).get('ok', False)
            dst_ok = (results.get(str(t.target_chat_id)) or {}).get('ok', False)
            reason = None if src_ok and dst_ok else (SOURCE_LOST if not src_ok else DEST_LOST)
            t.health_reason = reason
            if reason:
                t.joined_account_id = None
            senders = CloneRuleService._update_pool_status(t, sender_accounts, sender_results, checked_at)
            db.add(t)
            out.append({'target_id': t.id, 'ok': reason is None, 'reason': reason, 'senders': senders})
        await db.flush()
        return out

    @staticmethod
    async def _check_pool_membership(
        db: AsyncSession, rule: TgCloneRule, targets: list[TgCloneTarget]
    ) -> tuple[list[tuple[int, TgTelegramAccount]], dict[int, dict]]:
        sender_ids = [int(a) for a in CloneRuleService._sender_pool(rule) if int(a) != rule.account_id]
        sender_accounts = []
        for acc_id in sender_ids:
            account = await telegram_account_dao.get_by_scope(db, rule.tenant_id, rule.project_id, acc_id)
            if account:
                sender_accounts.append((acc_id, account))
        chat_ids = list(dict.fromkeys(t.target_chat_id for t in targets))
        semaphore = asyncio.Semaphore(3)

        async def check_sender(acc_id: int, account: TgTelegramAccount) -> tuple[int, dict]:
            async with semaphore:
                try:
                    return acc_id, await check_chat_membership(account, chat_ids)
                except Exception:
                    return acc_id, {}

        results = dict(await asyncio.gather(*starmap(check_sender, sender_accounts)))
        return sender_accounts, results

    @staticmethod
    def _update_pool_status(
        target: TgCloneTarget,
        sender_accounts: list[tuple[int, TgTelegramAccount]],
        sender_results: dict[int, dict],
        checked_at: str,
    ) -> dict[str, dict]:
        senders = {}
        joined = list(target.joined_account_ids or [])
        sender_status = dict(target.sender_status or {})
        for acc_id, _ in sender_accounts:
            account_results = sender_results.get(acc_id) or {}
            info = account_results.get('__account__') or account_results.get(str(target.target_chat_id)) or {}
            status = info.get('status') or 'error'
            can_post = info.get('can_post')
            status_entry = {'status': status, 'can_post': can_post, 'checked_at': checked_at}
            sender_status[str(acc_id)] = status_entry
            senders[str(acc_id)] = status_entry
            if can_post is True and acc_id not in joined:
                joined.append(acc_id)
            elif status in {'not_member', 'kicked', 'banned', 'muted'} or (status == 'member' and can_post is False):
                joined = [joined_id for joined_id in joined if joined_id != acc_id]
        target.joined_account_ids = joined
        target.sender_status = sender_status
        return senders

    @staticmethod
    async def update_target(
        *, db: AsyncSession, request: Request, rule_id: int, target_id: int, obj: CloneTargetParam
    ) -> TgCloneTarget:
        """改过滤/备注原地更新;源群或目标群变了则退役旧路线、新建路线(路由 ID 不跨群复用)。"""
        rule = await CloneRuleService.get(db=db, request=request, pk=rule_id)
        target = await clone_target_dao.get(db, target_id)
        if not target or target.rule_id != rule.id or target.status != 'active':
            raise errors.NotFoundError(msg='目标不存在')
        src_ref = CloneRuleService._chat_ref(obj.source_chat_id)
        dst_ref = CloneRuleService._chat_ref(obj.target_chat_id)
        same_src = src_ref in {target.source_chat_ref, str(target.source_chat_id)}
        same_dst = dst_ref in {target.target_chat_ref, str(target.target_chat_id)}
        if (
            same_src
            and same_dst
            and obj.source_topic_id == target.source_topic_id
            and obj.target_topic_id == target.target_topic_id
        ):
            target.filters = await CloneRuleService._normalize_filters(db, rule, obj.filters)
            target.remark = obj.remark
            db.add(target)
            await db.flush()
            return target
        await clone_target_dao.retire(db, target_id)
        await db.flush()
        return await CloneRuleService.add_target(db=db, request=request, rule_id=rule_id, obj=obj)

    @staticmethod
    async def retire_target(*, db: AsyncSession, request: Request, rule_id: int, target_id: int) -> int:
        rule = await CloneRuleService.get(db=db, request=request, pk=rule_id)
        target = await clone_target_dao.get(db, target_id)
        if not target or target.rule_id != rule.id:
            raise errors.NotFoundError(msg='目标不存在')
        return await clone_target_dao.retire(db, target_id)

    @staticmethod
    async def dry_run(*, db: AsyncSession, request: Request, pk: int) -> dict:
        """预览发布快照,无任何 Telegram 副作用(§7.1)"""
        rule = await CloneRuleService.get(db=db, request=request, pk=pk)
        targets = list(await clone_target_dao.get_active_by_rule(db, rule.id))
        problems: list[str] = []
        if not targets:
            problems.append('无 active 目标')
        seen: set[tuple] = set()
        for t in targets:
            k = (t.source_chat_id, t.source_topic_id, t.target_chat_id, t.target_topic_id)
            if t.source_chat_id == t.target_chat_id:
                problems.append(f'目标 {t.route_id} 源=目标自环')
            if k in seen:
                problems.append(f'目标 {t.route_id} 路由重复')
            seen.add(k)
        return {
            'rule_id': rule.id,
            'next_version': rule.current_version + 1,
            'targets': len(targets),
            'snapshot': _snapshot(rule, targets),
            'problems': problems,
        }

    @staticmethod
    async def publish(*, db: AsyncSession, request: Request, pk: int, expected_version: int) -> TgCloneRuleVersion:
        """发布:生成不可变快照,乐观锁校验 expected_version==current_version"""
        rule = await CloneRuleService.get(db=db, request=request, pk=pk)
        if rule.status == 'disabled':
            raise errors.RequestError(msg='规则已停用,不能发布')
        if rule.current_version != expected_version:
            raise errors.ConflictError(msg='版本已变更,请刷新后重试')
        targets = list(await clone_target_dao.get_active_by_rule(db, rule.id))
        if not targets:
            raise errors.RequestError(msg='无 active 目标,不能发布')
        routes = [_route_key(t) for t in targets]
        if len(set(routes)) != len(routes):
            raise errors.RequestError(msg='规则里有重复的源群→目标群路线,请先删除重复的再运行')
        # 运行时自动进群:按目标留存的原始标识(链接/ID)加入或验证成员关系,
        # 解析出的 chat_id 若变化(群迁移等)同步更新目标行
        if rule.enabled:
            await CloneRuleService._auto_join(db, rule, targets)
            # 进群发生在控制面子进程(独立连接):worker 的活客户端还不认识
            # 新加入的群,收不到它的频道更新 —— SyncChats 让监听号 warm 会话缓存
            await runtime_command_service.issue(
                db=db,
                request=request,
                account_id=rule.account_id,
                obj=CreateRuntimeCommandParam(type='SyncChats', dedup_key=f'syncchats-{uuid4_str()}'),
            )
        new_version = rule.current_version + 1
        ver = await clone_rule_version_dao.create(
            db,
            CreateCloneRuleVersionParam(
                rule_id=rule.id,
                tenant_id=rule.tenant_id,
                project_id=rule.project_id,
                version=new_version,
                snapshot=_snapshot(rule, targets),
                published_by=request.user.id,
                published_at=timezone.now(),
            ),
        )
        await db.flush()
        await clone_rule_dao.update(
            db,
            rule.id,
            {
                'current_version': new_version,
                'status': 'published',
            },
        )
        await CloneRuleService._notify_reload(db, request, rule)
        return ver

    @staticmethod
    async def get_versions(*, db: AsyncSession, request: Request, pk: int) -> list[TgCloneRuleVersion]:
        rule = await CloneRuleService.get(db=db, request=request, pk=pk)
        return list(await clone_rule_version_dao.get_all_by_rule(db, rule.id))

    @staticmethod
    async def delete(*, db: AsyncSession, request: Request, pk: int) -> int:
        rule = await CloneRuleService.get(db=db, request=request, pk=pk)
        deleted = await clone_rule_dao.delete(db, pk)
        await CloneRuleService._notify_reload(db, request, rule)
        return deleted


clone_rule_service: CloneRuleService = CloneRuleService()

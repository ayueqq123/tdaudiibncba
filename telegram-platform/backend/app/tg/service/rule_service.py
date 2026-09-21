from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tg.crud.crud_clone_rule import (
    clone_rule_dao,
    clone_rule_version_dao,
    clone_target_dao,
)
from backend.app.tg.crud.crud_membership import membership_dao
from backend.app.tg.crud.crud_project import project_dao
from backend.app.tg.crud.crud_telegram_account import telegram_account_dao
from backend.app.tg.model import TgCloneRule, TgCloneRuleVersion, TgCloneTarget
from backend.app.tg.schema.clone_rule import (
    CloneTargetParam,
    CreateCloneRuleParam,
    CreateCloneRuleVersionParam,
    CreateCloneTargetParam,
    UpdateCloneRuleParam,
)
from backend.common.exception import errors
from backend.utils.timezone import timezone


def _snapshot(rule: TgCloneRule, targets: list) -> dict:
    return {
        'rule': {
            'id': rule.id,
            'uuid': rule.uuid,
            'name': rule.name,
            'account_id': rule.account_id,
            'mode': rule.mode,
            'enabled': rule.enabled,
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


class CloneRuleService:
    """Clone 规则服务类(§6.2/§7.1:发布产生不可变快照)"""

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
        targets = await clone_target_dao.get_all_by_rule(db, rule.id)
        rule.targets = list(targets)
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
        await clone_rule_dao.create(db, obj)

    @staticmethod
    async def update(*, db: AsyncSession, request: Request, pk: int, obj: UpdateCloneRuleParam) -> int:
        await CloneRuleService.get(db=db, request=request, pk=pk)
        # 停用优先于快照:enabled=False 立即生效,不依赖下次发布
        return await clone_rule_dao.update(db, pk, obj)

    @staticmethod
    async def add_target(*, db: AsyncSession, request: Request, rule_id: int, obj: CloneTargetParam) -> TgCloneTarget:
        rule = await CloneRuleService.get(db=db, request=request, pk=rule_id)
        if rule.status == 'disabled':
            raise errors.RequestError(msg='规则已停用')
        if obj.source_chat_id == obj.target_chat_id and obj.source_topic_id == obj.target_topic_id:
            raise errors.RequestError(msg='禁止源=目标的自环')
        return await clone_target_dao.create(
            db,
            CreateCloneTargetParam(
                **obj.model_dump(),
                rule_id=rule_id,
                tenant_id=rule.tenant_id,
                project_id=rule.project_id,
            ),
        )

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
        return ver

    @staticmethod
    async def get_versions(*, db: AsyncSession, request: Request, pk: int) -> list[TgCloneRuleVersion]:
        rule = await CloneRuleService.get(db=db, request=request, pk=pk)
        return list(await clone_rule_version_dao.get_all_by_rule(db, rule.id))

    @staticmethod
    async def delete(*, db: AsyncSession, request: Request, pk: int) -> int:
        await CloneRuleService.get(db=db, request=request, pk=pk)
        return await clone_rule_dao.delete(db, pk)


clone_rule_service: CloneRuleService = CloneRuleService()

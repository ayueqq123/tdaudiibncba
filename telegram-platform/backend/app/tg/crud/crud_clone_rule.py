from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.tg.model import TgCloneRule, TgCloneRuleVersion, TgCloneTarget
from backend.app.tg.schema.clone_rule import (
    CreateCloneRuleParam,
    CreateCloneRuleVersionParam,
    CreateCloneTargetParam,
    UpdateCloneRuleParam,
)
from backend.utils.timezone import timezone


class CRUDCloneRule(CRUDPlus[TgCloneRule]):
    """Clone 规则数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> TgCloneRule | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_by_scope(self, db: AsyncSession, tenant_id: int, project_id: int, pk: int) -> TgCloneRule | None:
        return await self.select_model_by_column(db, id=pk, tenant_id=tenant_id, project_id=project_id, deleted=0)

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: int | None = None,
        project_id: int | None = None,
    ) -> Sequence[TgCloneRule]:
        filters: dict = {'deleted': 0}
        if tenant_id is not None:
            filters['tenant_id'] = tenant_id
        if project_id is not None:
            filters['project_id'] = project_id
        return await self.select_models(db, **filters)

    async def create(self, db: AsyncSession, obj: CreateCloneRuleParam) -> TgCloneRule:
        return await self.create_model(db, obj)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateCloneRuleParam | dict) -> int:
        return await self.update_model(db, pk, obj)

    async def delete(self, db: AsyncSession, pk: int) -> int:
        return await self.delete_model_by_column(
            db,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            id=pk,
            deleted=0,
        )


class CRUDCloneRuleVersion(CRUDPlus[TgCloneRuleVersion]):
    """Clone 规则版本(不可变快照)"""

    async def get_by_rule_version(self, db: AsyncSession, rule_id: int, version: int) -> TgCloneRuleVersion | None:
        return await self.select_model_by_column(db, rule_id=rule_id, version=version)

    async def create(self, db: AsyncSession, obj: CreateCloneRuleVersionParam) -> TgCloneRuleVersion:
        return await self.create_model(db, obj)

    async def get_latest(self, db: AsyncSession, rule_id: int) -> TgCloneRuleVersion | None:
        return await self.select_model_by_column(db, rule_id=rule_id, deleted=0, version__gt=0)

    async def get_all_by_rule(self, db: AsyncSession, rule_id: int) -> Sequence[TgCloneRuleVersion]:
        return await self.select_models(db, rule_id=rule_id, deleted=0)


class CRUDCloneTarget(CRUDPlus[TgCloneTarget]):
    """Clone 目标路由"""

    async def get(self, db: AsyncSession, pk: int) -> TgCloneTarget | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_all_by_rule(self, db: AsyncSession, rule_id: int) -> Sequence[TgCloneTarget]:
        return await self.select_models(db, rule_id=rule_id, deleted=0)

    async def get_active_by_rule(self, db: AsyncSession, rule_id: int) -> Sequence[TgCloneTarget]:
        return await self.select_models(db, rule_id=rule_id, status='active', deleted=0)

    async def create(self, db: AsyncSession, obj: CreateCloneTargetParam) -> TgCloneTarget:
        return await self.create_model(db, obj)

    async def retire(self, db: AsyncSession, pk: int) -> int:
        """退役不复用(§6.2):只改 status,不删行"""
        return await self.update_model(db, pk, {'status': 'retired'})


clone_rule_dao: CRUDCloneRule = CRUDCloneRule(TgCloneRule)
clone_rule_version_dao: CRUDCloneRuleVersion = CRUDCloneRuleVersion(TgCloneRuleVersion)
clone_target_dao: CRUDCloneTarget = CRUDCloneTarget(TgCloneTarget)

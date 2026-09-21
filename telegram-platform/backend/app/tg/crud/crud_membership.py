from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.tg.model import Membership
from backend.app.tg.schema.membership import CreateMembershipParam, UpdateMembershipParam
from backend.utils.timezone import timezone


class CRUDMembership(CRUDPlus[Membership]):
    """成员数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> Membership | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_by_scope(self, db: AsyncSession, tenant_id: int, project_id: int, user_id: int) -> Membership | None:
        return await self.select_model_by_column(
            db, tenant_id=tenant_id, project_id=project_id, user_id=user_id, deleted=0
        )

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: int | None = None,
        project_id: int | None = None,
        user_id: int | None = None,
    ) -> Sequence[Membership]:
        filters = {'deleted': 0}
        if tenant_id is not None:
            filters['tenant_id'] = tenant_id
        if project_id is not None:
            filters['project_id'] = project_id
        if user_id is not None:
            filters['user_id'] = user_id
        return await self.select_models(db, **filters)

    async def create(self, db: AsyncSession, obj: CreateMembershipParam) -> None:
        await self.create_model(db, obj)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateMembershipParam) -> int:
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


membership_dao: CRUDMembership = CRUDMembership(Membership)

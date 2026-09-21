from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.tg.model import Tenant
from backend.app.tg.schema.tenant import CreateTenantParam, UpdateTenantParam
from backend.utils.timezone import timezone


class CRUDTenant(CRUDPlus[Tenant]):
    """租户数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> Tenant | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_by_name(self, db: AsyncSession, name: str) -> Tenant | None:
        return await self.select_model_by_column(db, name=name, deleted=0)

    async def get_all(self, db: AsyncSession, name: str | None = None, status: int | None = None) -> Sequence[Tenant]:
        filters = {'deleted': 0}
        if name is not None:
            filters['name__like'] = f'%{name}%'
        if status is not None:
            filters['status'] = status
        return await self.select_models(db, **filters)

    async def create(self, db: AsyncSession, obj: CreateTenantParam) -> None:
        await self.create_model(db, obj)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateTenantParam) -> int:
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


tenant_dao: CRUDTenant = CRUDTenant(Tenant)

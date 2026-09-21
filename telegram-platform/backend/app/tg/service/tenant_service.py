from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tg.crud.crud_tenant import tenant_dao
from backend.app.tg.model import Tenant
from backend.app.tg.schema.tenant import CreateTenantParam, UpdateTenantParam
from backend.common.exception import errors


class TenantService:
    """租户服务类"""

    @staticmethod
    async def get(*, db: AsyncSession, pk: int) -> Tenant:
        tenant = await tenant_dao.get(db, pk)
        if not tenant:
            raise errors.NotFoundError(msg='租户不存在')
        return tenant

    @staticmethod
    async def get_all(*, db: AsyncSession, name: str | None = None, status: int | None = None) -> list[Tenant]:
        return list(await tenant_dao.get_all(db, name, status))

    @staticmethod
    async def create(*, db: AsyncSession, obj: CreateTenantParam) -> None:
        if await tenant_dao.get_by_name(db, obj.name):
            raise errors.ConflictError(msg='租户名称已存在')
        await tenant_dao.create(db, obj)

    @staticmethod
    async def update(*, db: AsyncSession, pk: int, obj: UpdateTenantParam) -> int:
        if not await tenant_dao.get(db, pk):
            raise errors.NotFoundError(msg='租户不存在')
        return await tenant_dao.update(db, pk, obj)

    @staticmethod
    async def delete(*, db: AsyncSession, pk: int) -> int:
        if not await tenant_dao.get(db, pk):
            raise errors.NotFoundError(msg='租户不存在')
        return await tenant_dao.delete(db, pk)


tenant_service: TenantService = TenantService()

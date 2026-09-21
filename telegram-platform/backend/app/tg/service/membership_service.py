from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tg.crud.crud_membership import membership_dao
from backend.app.tg.crud.crud_project import project_dao
from backend.app.tg.crud.crud_tenant import tenant_dao
from backend.app.tg.model import Membership
from backend.app.tg.schema.membership import CreateMembershipParam, UpdateMembershipParam
from backend.common.exception import errors


class MembershipService:
    """成员服务类(§6.1:资源查询必须匹配 membership 范围)"""

    @staticmethod
    async def get(*, db: AsyncSession, pk: int) -> Membership:
        membership = await membership_dao.get(db, pk)
        if not membership:
            raise errors.NotFoundError(msg='成员不存在')
        return membership

    @staticmethod
    async def get_all(
        *, db: AsyncSession, tenant_id: int | None = None, project_id: int | None = None, user_id: int | None = None
    ) -> list[Membership]:
        return list(await membership_dao.get_all(db, tenant_id, project_id, user_id))

    @staticmethod
    async def create(*, db: AsyncSession, obj: CreateMembershipParam) -> None:
        if not await tenant_dao.get(db, obj.tenant_id):
            raise errors.NotFoundError(msg='租户不存在')
        project = await project_dao.get(db, obj.project_id)
        if not project:
            raise errors.NotFoundError(msg='项目不存在')
        if project.tenant_id != obj.tenant_id:
            raise errors.ForbiddenError(msg='项目不属于该租户')
        if await membership_dao.get_by_scope(db, obj.tenant_id, obj.project_id, obj.user_id):
            raise errors.ConflictError(msg='该用户已在项目成员中')
        await membership_dao.create(db, obj)

    @staticmethod
    async def update(*, db: AsyncSession, pk: int, obj: UpdateMembershipParam) -> int:
        if not await membership_dao.get(db, pk):
            raise errors.NotFoundError(msg='成员不存在')
        return await membership_dao.update(db, pk, obj)

    @staticmethod
    async def delete(*, db: AsyncSession, pk: int) -> int:
        if not await membership_dao.get(db, pk):
            raise errors.NotFoundError(msg='成员不存在')
        return await membership_dao.delete(db, pk)


membership_service: MembershipService = MembershipService()

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tg.crud.crud_project import project_dao
from backend.app.tg.crud.crud_tenant import tenant_dao
from backend.app.tg.model import Project
from backend.app.tg.schema.project import CreateProjectParam, UpdateProjectParam
from backend.common.exception import errors


class ProjectService:
    """项目服务类"""

    @staticmethod
    async def get(*, db: AsyncSession, pk: int) -> Project:
        project = await project_dao.get(db, pk)
        if not project:
            raise errors.NotFoundError(msg='项目不存在')
        return project

    @staticmethod
    async def get_all(
        *, db: AsyncSession, tenant_id: int | None = None, name: str | None = None, status: int | None = None
    ) -> list[Project]:
        return list(await project_dao.get_all(db, tenant_id, name, status))

    @staticmethod
    async def create(*, db: AsyncSession, obj: CreateProjectParam) -> None:
        if not await tenant_dao.get(db, obj.tenant_id):
            raise errors.NotFoundError(msg='租户不存在')
        if await project_dao.get_by_tenant_and_name(db, obj.tenant_id, obj.name):
            raise errors.ConflictError(msg='该租户下项目名称已存在')
        await project_dao.create(db, obj)

    @staticmethod
    async def update(*, db: AsyncSession, pk: int, obj: UpdateProjectParam) -> int:
        if not await project_dao.get(db, pk):
            raise errors.NotFoundError(msg='项目不存在')
        if not await tenant_dao.get(db, obj.tenant_id):
            raise errors.NotFoundError(msg='租户不存在')
        return await project_dao.update(db, pk, obj)

    @staticmethod
    async def delete(*, db: AsyncSession, pk: int) -> int:
        if not await project_dao.get(db, pk):
            raise errors.NotFoundError(msg='项目不存在')
        return await project_dao.delete(db, pk)


project_service: ProjectService = ProjectService()

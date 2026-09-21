from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.tg.model import Project
from backend.app.tg.schema.project import CreateProjectParam, UpdateProjectParam
from backend.utils.timezone import timezone


class CRUDProject(CRUDPlus[Project]):
    """项目数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> Project | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_by_tenant_and_name(self, db: AsyncSession, tenant_id: int, name: str) -> Project | None:
        return await self.select_model_by_column(db, tenant_id=tenant_id, name=name, deleted=0)

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: int | None = None,
        name: str | None = None,
        status: int | None = None,
    ) -> Sequence[Project]:
        filters = {'deleted': 0}
        if tenant_id is not None:
            filters['tenant_id'] = tenant_id
        if name is not None:
            filters['name__like'] = f'%{name}%'
        if status is not None:
            filters['status'] = status
        return await self.select_models(db, **filters)

    async def create(self, db: AsyncSession, obj: CreateProjectParam) -> None:
        await self.create_model(db, obj)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateProjectParam) -> int:
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


project_dao: CRUDProject = CRUDProject(Project)

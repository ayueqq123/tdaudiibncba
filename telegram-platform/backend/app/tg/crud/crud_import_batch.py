from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.tg.model import TgImportBatch
from backend.app.tg.schema.import_batch import CreateImportBatchParam


class CRUDTgImportBatch(CRUDPlus[TgImportBatch]):
    """Session 导入批次数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> TgImportBatch | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_by_scope(self, db: AsyncSession, tenant_id: int, project_id: int, pk: int) -> TgImportBatch | None:
        return await self.select_model_by_column(db, id=pk, tenant_id=tenant_id, project_id=project_id, deleted=0)

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: int | None = None,
        project_id: int | None = None,
    ) -> Sequence[TgImportBatch]:
        filters: dict = {'deleted': 0}
        if tenant_id is not None:
            filters['tenant_id'] = tenant_id
        if project_id is not None:
            filters['project_id'] = project_id
        return await self.select_models(db, **filters)

    async def create(self, db: AsyncSession, obj: CreateImportBatchParam) -> TgImportBatch:
        return await self.create_model(db, obj)

    async def update(self, db: AsyncSession, pk: int, obj: dict) -> int:
        return await self.update_model(db, pk, obj)


import_batch_dao: CRUDTgImportBatch = CRUDTgImportBatch(TgImportBatch)

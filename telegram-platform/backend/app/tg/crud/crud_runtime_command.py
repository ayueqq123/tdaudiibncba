from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.tg.model import TgRuntimeCommand
from backend.app.tg.schema.runtime_command import CreateRuntimeCommandInternalParam
from backend.utils.timezone import timezone


class CRUDRuntimeCommand(CRUDPlus[TgRuntimeCommand]):
    """运行时命令数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> TgRuntimeCommand | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_by_dedup_key(self, db: AsyncSession, dedup_key: str) -> TgRuntimeCommand | None:
        return await self.select_model_by_column(db, dedup_key=dedup_key, deleted=0)

    async def get_pending_by_account(self, db: AsyncSession, account_id: int) -> Sequence[TgRuntimeCommand]:
        return await self.select_models(db, account_id=account_id, status='pending', deleted=0)

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: int | None = None,
        project_id: int | None = None,
        account_id: int | None = None,
        status: str | None = None,
    ) -> Sequence[TgRuntimeCommand]:
        filters: dict = {'deleted': 0}
        filters.update({
            k: v
            for k, v in {
                'tenant_id': tenant_id,
                'project_id': project_id,
                'account_id': account_id,
                'status': status,
            }.items()
            if v is not None
        })
        return await self.select_models(db, **filters)

    async def create(self, db: AsyncSession, obj: CreateRuntimeCommandInternalParam) -> TgRuntimeCommand:
        return await self.create_model(db, obj)

    async def update(self, db: AsyncSession, pk: int, obj: dict) -> int:
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


runtime_command_dao: CRUDRuntimeCommand = CRUDRuntimeCommand(TgRuntimeCommand)

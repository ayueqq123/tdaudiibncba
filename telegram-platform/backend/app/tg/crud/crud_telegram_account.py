from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.tg.model import TgTelegramAccount
from backend.app.tg.schema.telegram_account import CreateTgAccountParam, UpdateTgAccountParam
from backend.utils.timezone import timezone


class CRUDTgTelegramAccount(CRUDPlus[TgTelegramAccount]):
    """Telegram 账号数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> TgTelegramAccount | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_by_scope(
        self, db: AsyncSession, tenant_id: int, project_id: int, pk: int
    ) -> TgTelegramAccount | None:
        """限定 (tenant, project) 范围查询,跨项目返回 None(§6.1)"""
        return await self.select_model_by_column(db, id=pk, tenant_id=tenant_id, project_id=project_id, deleted=0)

    async def get_by_tg_user(self, db: AsyncSession, telegram_user_id: int) -> TgTelegramAccount | None:
        """当前部署内同一 Telegram 身份默认唯一(§6.2)"""
        return await self.select_model_by_column(db, telegram_user_id=telegram_user_id, deleted=0)

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: int | None = None,
        project_id: int | None = None,
        status: str | None = None,
    ) -> Sequence[TgTelegramAccount]:
        filters: dict = {'deleted': 0}
        if tenant_id is not None:
            filters['tenant_id'] = tenant_id
        if project_id is not None:
            filters['project_id'] = project_id
        if status is not None:
            filters['observed_status'] = status
        return await self.select_models(db, **filters)

    async def create(self, db: AsyncSession, obj: CreateTgAccountParam) -> TgTelegramAccount:
        return await self.create_model(db, obj)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateTgAccountParam | dict) -> int:
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


telegram_account_dao: CRUDTgTelegramAccount = CRUDTgTelegramAccount(TgTelegramAccount)

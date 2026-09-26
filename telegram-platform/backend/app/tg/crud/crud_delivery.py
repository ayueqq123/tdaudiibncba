from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.tg.model.delivery import TgDeliveryAttempt, TgDeliveryJob, TgMessageMap


class CRUDDeliveryJob(CRUDPlus[TgDeliveryJob]):
    """投递任务数据库操作类(平台侧查询 + 受限状态写)"""

    async def get(self, db: AsyncSession, pk: str) -> TgDeliveryJob | None:
        return await self.select_model_by_column(db, id=pk)

    async def get_all(
        self,
        db: AsyncSession,
        tenant_uuid: str | None = None,
        project_uuid: str | None = None,
        account_uuid: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        allowed_tenants: set[str] | None = None,
    ) -> Sequence[TgDeliveryJob]:
        filters = {
            k: v
            for k, v in {
                'tenant_id': tenant_uuid,
                'project_id': project_uuid,
                'account_id': account_uuid,
                'status': status,
            }.items()
            if v is not None
        }
        whereclause = [getattr(TgDeliveryJob, k) == v for k, v in filters.items()]
        if allowed_tenants is not None:
            whereclause.append(TgDeliveryJob.tenant_id.in_(allowed_tenants))
        stmt = (
            sa.select(TgDeliveryJob)
            .where(*whereclause)
            .order_by(TgDeliveryJob.created_at.desc())
            .offset(offset or 0)
            .limit(limit or 500)
        )
        return (await db.execute(stmt)).scalars().all()

    async def count_all(
        self,
        db: AsyncSession,
        tenant_uuid: str | None = None,
        project_uuid: str | None = None,
        account_uuid: str | None = None,
        status: str | None = None,
        allowed_tenants: set[str] | None = None,
    ) -> int:
        filters = {
            k: v
            for k, v in {
                'tenant_id': tenant_uuid,
                'project_id': project_uuid,
                'account_id': account_uuid,
                'status': status,
            }.items()
            if v is not None
        }
        whereclause = [getattr(TgDeliveryJob, k) == v for k, v in filters.items()]
        if allowed_tenants is not None:
            whereclause.append(TgDeliveryJob.tenant_id.in_(allowed_tenants))
        stmt = sa.select(sa.func.count()).select_from(TgDeliveryJob).where(*whereclause)
        return (await db.execute(stmt)).scalar() or 0

    async def get_by_idempotency_key(self, db: AsyncSession, key: str) -> TgDeliveryJob | None:
        return await self.select_model_by_column(db, idempotency_key=key)

    async def update(self, db: AsyncSession, pk: str, obj: dict) -> int:
        return await self.update_model_by_column(db, obj, id=pk)


class CRUDDeliveryAttempt(CRUDPlus[TgDeliveryAttempt]):
    """投递尝试数据库操作类(append-only,平台侧只读)"""

    async def get_by_job(self, db: AsyncSession, job_id: str) -> Sequence[TgDeliveryAttempt]:
        return await self.select_models(db, job_id=job_id)


class CRUDMessageMap(CRUDPlus[TgMessageMap]):
    """消息映射数据库操作类(平台侧只读)"""

    async def get_by_source(
        self, db: AsyncSession, source_scope: str, source_chat_id: int, source_message_id: int
    ) -> Sequence[TgMessageMap]:
        return await self.select_models(
            db,
            source_scope=source_scope,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
        )

    async def get_by_route(self, db: AsyncSession, route_id: str) -> Sequence[TgMessageMap]:
        return await self.select_models(db, route_id=route_id)


delivery_job_dao: CRUDDeliveryJob = CRUDDeliveryJob(TgDeliveryJob)
delivery_attempt_dao: CRUDDeliveryAttempt = CRUDDeliveryAttempt(TgDeliveryAttempt)
message_map_dao: CRUDMessageMap = CRUDMessageMap(TgMessageMap)

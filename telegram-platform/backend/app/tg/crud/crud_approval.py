from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.app.tg.model import TgApproval, TgReplyCandidate
from backend.app.tg.schema.approval import CreateApprovalParam, CreateReplyCandidateParam


class CRUDReplyCandidate(CRUDPlus[TgReplyCandidate]):
    """回复候选数据库操作类(不可变:只建不改)"""

    async def get(self, db: AsyncSession, pk: int) -> TgReplyCandidate | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: int | None = None,
        project_id: int | None = None,
        account_id: int | None = None,
        status: str | None = None,
    ) -> Sequence[TgReplyCandidate]:
        filters = {
            k: v
            for k, v in {
                'tenant_id': tenant_id,
                'project_id': project_id,
                'account_id': account_id,
                'status': status,
            }.items()
            if v is not None
        }
        return await self.select_models(db, deleted=0, **filters)

    async def create(self, db: AsyncSession, obj: CreateReplyCandidateParam) -> TgReplyCandidate:
        return await self.create_model(db, obj)

    async def update_status(self, db: AsyncSession, pk: int, status: str) -> int:
        return await self.update_model(db, pk, {'status': status})


class CRUDApproval(CRUDPlus[TgApproval]):
    """审批数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> TgApproval | None:
        return await self.select_model_by_column(db, id=pk, deleted=0)

    async def get_pending_by_candidate(self, db: AsyncSession, candidate_id: int) -> TgApproval | None:
        return await self.select_model_by_column(db, candidate_id=candidate_id, status='pending', deleted=0)

    async def get_all(
        self,
        db: AsyncSession,
        tenant_id: int | None = None,
        project_id: int | None = None,
        status: str | None = None,
    ) -> Sequence[TgApproval]:
        filters = {
            k: v
            for k, v in {
                'tenant_id': tenant_id,
                'project_id': project_id,
                'status': status,
            }.items()
            if v is not None
        }
        return await self.select_models(db, deleted=0, **filters)

    async def create(self, db: AsyncSession, obj: CreateApprovalParam) -> TgApproval:
        return await self.create_model(db, obj)

    async def update(self, db: AsyncSession, pk: int, obj: dict) -> int:
        return await self.update_model(db, pk, obj)


reply_candidate_dao: CRUDReplyCandidate = CRUDReplyCandidate(TgReplyCandidate)
approval_dao: CRUDApproval = CRUDApproval(TgApproval)

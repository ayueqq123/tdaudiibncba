from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tg.crud.crud_approval import approval_dao, reply_candidate_dao
from backend.app.tg.crud.crud_membership import membership_dao
from backend.app.tg.crud.crud_telegram_account import telegram_account_dao
from backend.app.tg.model import TgApproval, TgReplyCandidate
from backend.app.tg.schema.approval import (
    ApproveCandidateParam,
    CreateApprovalParam,
    CreateReplyCandidateParam,
    RejectCandidateParam,
)
from backend.common.exception import errors
from backend.utils.timezone import timezone


class ApprovalService:
    """审批服务(§10.1:approval 绑定不可变候选版本 + hash + 有效期)"""

    @staticmethod
    async def _check_scope(db: AsyncSession, request: Request, tenant_id: int, project_id: int) -> None:
        if request.user.is_superuser:
            return
        if not await membership_dao.get_by_scope(db, tenant_id, project_id, request.user.id):
            raise errors.ForbiddenError(msg='无该项目权限')

    @staticmethod
    async def create_candidate(
        *, db: AsyncSession, request: Request, obj: CreateReplyCandidateParam
    ) -> TgReplyCandidate:
        await ApprovalService._check_scope(db, request, obj.tenant_id, obj.project_id)
        account = await telegram_account_dao.get_by_scope(db, obj.tenant_id, obj.project_id, obj.account_id)
        if not account:
            raise errors.NotFoundError(msg='账号不存在于该项目')
        candidate = await reply_candidate_dao.create(db, obj)
        await db.flush()
        # 候选创建即挂 pending 审批单;审批单绑定 candidate.version + hash + 有效期
        await approval_dao.create(
            db,
            CreateApprovalParam(
                tenant_id=obj.tenant_id,
                project_id=obj.project_id,
                candidate_id=candidate.id,
                candidate_version=candidate.version,
                content_hash=candidate.content_hash,
                expires_at=candidate.expires_at,
                status='pending',
            ),
        )
        return candidate

    @staticmethod
    async def _decide(
        *,
        db: AsyncSession,
        request: Request,
        pk: int,
        expect_version: int,
        expect_hash: str,
        decision: str,
        reason: str | None,
    ) -> TgApproval:
        approval = await approval_dao.get(db, pk)
        if not approval:
            raise errors.NotFoundError(msg='审批单不存在')
        await ApprovalService._check_scope(db, request, approval.tenant_id, approval.project_id)
        if approval.status != 'pending':
            raise errors.RequestError(msg='审批已处理')
        now = timezone.now()
        expires = approval.expires_at
        if expires is not None and expires < now:
            await approval_dao.update(db, pk, {'status': 'expired'})
            raise errors.RequestError(msg='审批已过期')
        candidate = await reply_candidate_dao.get(db, approval.candidate_id)
        if not candidate:
            raise errors.NotFoundError(msg='候选不存在')
        # 版本/内容 hash 校验:任何变化都必须重审,旧审批失效
        if candidate.version != expect_version or candidate.version != approval.candidate_version:
            raise errors.ConflictError(msg='候选版本已变更,审批失效')
        if candidate.content_hash != expect_hash or candidate.content_hash != approval.content_hash:
            raise errors.ConflictError(msg='内容 hash 不匹配,审批失效')

        await approval_dao.update(
            db,
            pk,
            {
                'status': decision,
                'reviewer_id': request.user.id,
                'decided_at': now,
                'reason': reason,
            },
        )
        await reply_candidate_dao.update_status(db, candidate.id, decision)
        return await approval_dao.get(db, pk)

    @staticmethod
    async def approve(*, db: AsyncSession, request: Request, pk: int, obj: ApproveCandidateParam) -> TgApproval:
        return await ApprovalService._decide(
            db=db,
            request=request,
            pk=pk,
            expect_version=obj.candidate_version,
            expect_hash=obj.content_hash,
            decision='approved',
            reason=obj.reason,
        )

    @staticmethod
    async def reject(*, db: AsyncSession, request: Request, pk: int, obj: RejectCandidateParam) -> TgApproval:
        return await ApprovalService._decide(
            db=db,
            request=request,
            pk=pk,
            expect_version=obj.candidate_version,
            expect_hash=obj.content_hash,
            decision='rejected',
            reason=obj.reason,
        )

    @staticmethod
    async def get_all(
        *,
        db: AsyncSession,
        request: Request,
        tenant_id: int | None = None,
        project_id: int | None = None,
        status: str | None = None,
    ) -> list[TgApproval]:
        approvals = list(await approval_dao.get_all(db, tenant_id, project_id, status))
        if request.user.is_superuser:
            return approvals
        memberships = await membership_dao.get_all(db, user_id=request.user.id)
        scopes = {(m.tenant_id, m.project_id) for m in memberships}
        return [a for a in approvals if (a.tenant_id, a.project_id) in scopes]

    @staticmethod
    async def get_candidates(
        *,
        db: AsyncSession,
        request: Request,
        tenant_id: int | None = None,
        project_id: int | None = None,
        account_id: int | None = None,
        status: str | None = None,
    ) -> list[TgReplyCandidate]:
        candidates = list(await reply_candidate_dao.get_all(db, tenant_id, project_id, account_id, status))
        if request.user.is_superuser:
            return candidates
        memberships = await membership_dao.get_all(db, user_id=request.user.id)
        scopes = {(m.tenant_id, m.project_id) for m in memberships}
        return [c for c in candidates if (c.tenant_id, c.project_id) in scopes]


approval_service: ApprovalService = ApprovalService()

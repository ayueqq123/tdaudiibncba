from datetime import timedelta

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tg.crud.crud_membership import membership_dao
from backend.app.tg.crud.crud_runtime_command import runtime_command_dao
from backend.app.tg.crud.crud_telegram_account import telegram_account_dao
from backend.app.tg.model import TgRuntimeCommand
from backend.app.tg.schema.runtime_command import (
    AckRuntimeCommandParam,
    CreateRuntimeCommandInternalParam,
    CreateRuntimeCommandParam,
)
from backend.common.exception import errors
from backend.database.db import uuid4_str
from backend.utils.timezone import timezone

_ACK_OK = {'acknowledged', 'done', 'rejected'}


class RuntimeCommandService:
    """运行时命令服务(§6.2/§12:重放幂等,expected_generation 防过期命令)"""

    @staticmethod
    async def _check_scope(db: AsyncSession, request: Request, tenant_id: int, project_id: int) -> None:
        if request.user.is_superuser:
            return
        if not await membership_dao.get_by_scope(db, tenant_id, project_id, request.user.id):
            raise errors.ForbiddenError(msg='无该项目权限')

    @staticmethod
    async def issue(
        *, db: AsyncSession, request: Request, account_id: int, obj: CreateRuntimeCommandParam
    ) -> TgRuntimeCommand:
        account = await telegram_account_dao.get(db, account_id)
        if not account:
            raise errors.NotFoundError(msg='账号不存在')
        await RuntimeCommandService._check_scope(db, request, account.tenant_id, account.project_id)

        if obj.dedup_key:
            existing = await runtime_command_dao.get_by_dedup_key(db, obj.dedup_key)
            if existing:
                # 幂等重放:返回原命令,不重复下发
                return existing

        cmd = await runtime_command_dao.create(
            db,
            CreateRuntimeCommandInternalParam(
                tenant_id=account.tenant_id,
                project_id=account.project_id,
                account_id=account_id,
                type=obj.type,
                payload=obj.payload,
                expected_generation=obj.expected_generation,
                dedup_key=obj.dedup_key or uuid4_str(),
                issued_by=request.user.id,
                deadline=timezone.now() + timedelta(minutes=30),
                trace_id=getattr(request.state, 'trace_id', None),
            ),
        )
        await db.flush()
        return cmd

    @staticmethod
    async def get_pending(*, db: AsyncSession, account_id: int) -> list[TgRuntimeCommand]:
        """Worker 拉取待执行命令(过期即视为失效)"""
        now = timezone.now()
        pending = await runtime_command_dao.get_pending_by_account(db, account_id)
        return [c for c in pending if c.deadline is None or c.deadline > now]

    @staticmethod
    async def ack(*, db: AsyncSession, command_id: int, obj: AckRuntimeCommandParam) -> TgRuntimeCommand:
        cmd = await runtime_command_dao.get(db, command_id)
        if not cmd:
            raise errors.NotFoundError(msg='命令不存在')
        if obj.status not in _ACK_OK:
            raise errors.RequestError(msg='非法回执状态')
        now = timezone.now()
        updates: dict = {'status': obj.status, 'result': obj.result}
        if obj.status == 'acknowledged':
            updates['acked_at'] = now
        else:
            updates['finished_at'] = now
        await runtime_command_dao.update(db, command_id, updates)
        return await runtime_command_dao.get(db, command_id)

    @staticmethod
    async def get_all(
        *,
        db: AsyncSession,
        request: Request,
        tenant_id: int | None = None,
        project_id: int | None = None,
        account_id: int | None = None,
        status: str | None = None,
    ) -> list[TgRuntimeCommand]:
        cmds = list(await runtime_command_dao.get_all(db, tenant_id, project_id, account_id, status))
        if request.user.is_superuser:
            return cmds
        memberships = await membership_dao.get_all(db, user_id=request.user.id)
        scopes = {(m.tenant_id, m.project_id) for m in memberships}
        return [c for c in cmds if (c.tenant_id, c.project_id) in scopes]


runtime_command_service: RuntimeCommandService = RuntimeCommandService()

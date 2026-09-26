from typing import Any
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tg.crud.crud_delivery import (
    delivery_attempt_dao,
    delivery_job_dao,
    message_map_dao,
)
from backend.app.tg.crud.crud_membership import membership_dao
from backend.app.tg.crud.crud_project import project_dao
from backend.app.tg.crud.crud_telegram_account import telegram_account_dao
from backend.app.tg.crud.crud_tenant import tenant_dao
from backend.app.tg.model import TgDeliveryJob
from backend.common.exception import errors

# §8.2:retry 只放行可重试终态;uncertain 必须走单独人工决策
_RETRYABLE = {'failed_permanent', 'dead_letter'}
_CANCELLABLE = {'pending', 'waiting_approval', 'ready', 'retry_wait', 'blocked', 'uncertain'}


class DeliveryService:
    """投递查询与任务控制(§7/§8.2:每目标状态可见;uncertain 不走普通重试)"""

    @staticmethod
    async def _scope_uuids(
        db: AsyncSession, request: Request, tenant_id: int | None, project_id: int | None, account_id: int | None
    ) -> tuple[set[str] | None, str | None, str | None, str | None]:
        """返回 (允许的 tenant_uuid 集合|None=不过滤, tenant_uuid, project_uuid, account_uuid)。

        非超管:把 int 范围参数解析成 runtime 表里的 uuid 字符串,
        同时收集该用户全部 membership scope 用于过滤。
        """
        tenant_uuid = project_uuid = account_uuid = None
        if tenant_id is not None:
            t = await tenant_dao.get(db, tenant_id)
            if not t:
                raise errors.NotFoundError(msg='租户不存在')
            tenant_uuid = t.uuid
        if project_id is not None:
            p = await project_dao.get(db, project_id)
            if not p:
                raise errors.NotFoundError(msg='项目不存在')
            project_uuid = p.uuid
        if account_id is not None:
            a = await telegram_account_dao.get(db, account_id)
            if not a:
                raise errors.NotFoundError(msg='账号不存在')
            account_uuid = a.uuid

        allowed_tenants: set[str] | None = None
        if not request.user.is_superuser:
            memberships = await membership_dao.get_all(db, user_id=request.user.id)
            if not memberships:
                return set(), tenant_uuid, project_uuid, account_uuid
            tenant_ids = {m.tenant_id for m in memberships}
            tenants = [await tenant_dao.get(db, t) for t in tenant_ids]
            allowed_tenants = {t.uuid for t in tenants if t}
            if tenant_uuid and tenant_uuid not in allowed_tenants:
                raise errors.ForbiddenError(msg='无该租户权限')
        return allowed_tenants, tenant_uuid, project_uuid, account_uuid

    @staticmethod
    async def _check_job_scope(db: AsyncSession, request: Request, job: TgDeliveryJob) -> None:
        if request.user.is_superuser:
            return
        t = await tenant_dao.select_model_by_column(db, uuid=job.tenant_id)
        p = await project_dao.select_model_by_column(db, uuid=job.project_id)
        if not t or not p:
            raise errors.NotFoundError(msg='任务不存在')
        if not await membership_dao.get_by_scope(db, t.id, p.id, request.user.id):
            raise errors.ForbiddenError(msg='无该项目权限')

    @staticmethod
    async def get(*, db: AsyncSession, request: Request, pk: str) -> TgDeliveryJob:
        job = await delivery_job_dao.get(db, pk)
        if not job:
            raise errors.NotFoundError(msg='投递任务不存在')
        await DeliveryService._check_job_scope(db, request, job)
        return job

    @staticmethod
    async def get_detail(*, db: AsyncSession, request: Request, pk: str) -> TgDeliveryJob:
        job = await DeliveryService.get(db=db, request=request, pk=pk)
        attempts = list(await delivery_attempt_dao.get_by_job(db, job.id))
        attempts.sort(key=lambda a: a.attempt_no)
        maps = await message_map_dao.get_by_source(db, job.source_scope, job.source_chat_id, job.source_message_id)
        job.attempts = list(attempts)
        job.message_maps = [
            {
                'id': m.id,
                'route_id': m.route_id,
                'target_chat_id': m.target_chat_id,
                'target_topic_id': m.target_topic_id,
                'target_message_id': m.target_message_id,
                'status': m.status,
                'deleted_at': m.deleted_at,
            }
            for m in maps
        ]
        return job

    @staticmethod
    async def get_all(
        *,
        db: AsyncSession,
        request: Request,
        tenant_id: int | None = None,
        project_id: int | None = None,
        account_id: int | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        allowed, tenant_uuid, project_uuid, account_uuid = await DeliveryService._scope_uuids(
            db, request, tenant_id, project_id, account_id
        )
        if allowed is not None and not allowed:
            return {'total': 0, 'page': page, 'size': size, 'items': []}
        page = max(page, 1)
        size = min(max(size, 1), 200)
        total = await delivery_job_dao.count_all(
            db, tenant_uuid, project_uuid, account_uuid, status, allowed_tenants=allowed
        )
        jobs = list(
            await delivery_job_dao.get_all(
                db,
                tenant_uuid,
                project_uuid,
                account_uuid,
                status,
                limit=size,
                offset=(page - 1) * size,
                allowed_tenants=allowed,
            )
        )
        # 账号 uuid → 展示标签(优先 username,其次手机号/uid)
        account_uuids = {j.account_id for j in jobs if j.account_id}
        accounts = list(await telegram_account_dao.get_all(db, None, None, None)) if account_uuids else []
        labels = {
            a.uuid: (f'@{a.username}' if a.username else a.phone or str(a.telegram_user_id or a.id))
            for a in accounts
            if a.uuid in account_uuids
        }
        items = []
        for j in jobs:
            d = {c.name: getattr(j, c.name) for c in TgDeliveryJob.__table__.columns}
            d['account_label'] = labels.get(j.account_id, j.account_id[:8])
            items.append(d)
        return {'total': total, 'page': page, 'size': size, 'items': items}

    @staticmethod
    async def retry(*, db: AsyncSession, request: Request, pk: str) -> int:
        job = await DeliveryService.get(db=db, request=request, pk=pk)
        if job.status == 'uncertain':
            # §8.2:uncertain 不能走普通重试,需人工核实后走专门决策
            raise errors.RequestError(msg='uncertain 状态需人工核实后处理,不能普通重试')
        if job.status not in _RETRYABLE:
            raise errors.RequestError(msg=f'当前状态 {job.status} 不可重试')
        return await delivery_job_dao.update(db, pk, {'status': 'ready', 'next_attempt_at': None})

    @staticmethod
    async def cancel(*, db: AsyncSession, request: Request, pk: str) -> int:
        job = await DeliveryService.get(db=db, request=request, pk=pk)
        if job.status not in _CANCELLABLE:
            raise errors.RequestError(msg=f'当前状态 {job.status} 不可取消')
        return await delivery_job_dao.update(db, pk, {'status': 'cancelled'})


delivery_service: DeliveryService = DeliveryService()

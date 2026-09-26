from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.app.tg.schema.delivery import (
    CancelDeliveryParam,
    GetDeliveryJobFull,
    GetDeliveryJobPage,
    RetryDeliveryParam,
)
from backend.app.tg.service.delivery_service import delivery_service
from backend.common.response.response_schema import (
    ResponseModel,
    ResponseSchemaModel,
    response_base,
)
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction

router = APIRouter()


@router.get('/{job_id}', summary='投递任务详情(含尝试与映射)', dependencies=[DependsJwtAuth])
async def get_delivery(
    db: CurrentSession, request: Request, job_id: Annotated[str, Path(description='任务 ID')]
) -> ResponseSchemaModel[GetDeliveryJobFull]:
    data = await delivery_service.get_detail(db=db, request=request, pk=job_id)
    return response_base.success(data=data)


@router.get('', summary='投递任务列表', dependencies=[DependsJwtAuth])
async def get_deliveries(
    db: CurrentSession,
    request: Request,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
    account_id: Annotated[int | None, Query(description='账号 ID')] = None,
    status: Annotated[str | None, Query(description='投递状态')] = None,
    page: Annotated[int, Query(description='页码', ge=1)] = 1,
    size: Annotated[int, Query(description='每页条数', ge=1, le=200)] = 20,
) -> ResponseSchemaModel[GetDeliveryJobPage]:
    data = await delivery_service.get_all(
        db=db,
        request=request,
        tenant_id=tenant_id,
        project_id=project_id,
        account_id=account_id,
        status=status,
        page=page,
        size=size,
    )
    return response_base.success(data=data)


@router.post(
    '/{job_id}/retry',
    summary='重试投递任务',
    dependencies=[Depends(RequestPermission('tg:delivery:retry')), DependsRBAC],
)
async def retry_delivery(
    db: CurrentSessionTransaction,
    request: Request,
    job_id: Annotated[str, Path(description='任务 ID')],
    obj: RetryDeliveryParam,
) -> ResponseModel:
    count = await delivery_service.retry(db=db, request=request, pk=job_id)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.post(
    '/{job_id}/cancel',
    summary='取消投递任务',
    dependencies=[Depends(RequestPermission('tg:delivery:cancel')), DependsRBAC],
)
async def cancel_delivery(
    db: CurrentSessionTransaction,
    request: Request,
    job_id: Annotated[str, Path(description='任务 ID')],
    obj: CancelDeliveryParam,
) -> ResponseModel:
    count = await delivery_service.cancel(db=db, request=request, pk=job_id)
    if count > 0:
        return response_base.success()
    return response_base.fail()

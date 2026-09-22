from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.app.tg.schema.approval import (
    ApproveCandidateParam,
    CreateReplyCandidateParam,
    GetApprovalDetail,
    GetReplyCandidateDetail,
    RejectCandidateParam,
)
from backend.app.tg.service.approval_service import approval_service
from backend.common.response.response_schema import (
    ResponseSchemaModel,
    response_base,
)
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction

router = APIRouter()


@router.get('', summary='审批单列表', dependencies=[DependsJwtAuth])
async def get_approvals(
    db: CurrentSession,
    request: Request,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
    status: Annotated[str | None, Query(description='审批状态')] = None,
) -> ResponseSchemaModel[list[GetApprovalDetail]]:
    data = await approval_service.get_all(
        db=db, request=request, tenant_id=tenant_id, project_id=project_id, status=status
    )
    return response_base.success(data=data)


@router.post(
    '/{pk}/approve',
    summary='审批通过',
    dependencies=[Depends(RequestPermission('tg:approval:decide')), DependsRBAC],
)
async def approve(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='审批单 ID')],
    obj: ApproveCandidateParam,
) -> ResponseSchemaModel[GetApprovalDetail]:
    data = await approval_service.approve(db=db, request=request, pk=pk, obj=obj)
    return response_base.success(data=data)


@router.post(
    '/{pk}/reject',
    summary='审批拒绝',
    dependencies=[Depends(RequestPermission('tg:approval:decide')), DependsRBAC],
)
async def reject(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='审批单 ID')],
    obj: RejectCandidateParam,
) -> ResponseSchemaModel[GetApprovalDetail]:
    data = await approval_service.reject(db=db, request=request, pk=pk, obj=obj)
    return response_base.success(data=data)


@router.get('/candidates', summary='回复候选列表', dependencies=[DependsJwtAuth])
async def get_candidates(
    db: CurrentSession,
    request: Request,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
    account_id: Annotated[int | None, Query(description='账号 ID')] = None,
    status: Annotated[str | None, Query(description='候选状态')] = None,
) -> ResponseSchemaModel[list[GetReplyCandidateDetail]]:
    data = await approval_service.get_candidates(
        db=db,
        request=request,
        tenant_id=tenant_id,
        project_id=project_id,
        account_id=account_id,
        status=status,
    )
    return response_base.success(data=data)


@router.post(
    '/candidates',
    summary='创建回复候选(挂起审批)',
    dependencies=[Depends(RequestPermission('tg:approval:create')), DependsRBAC],
)
async def create_candidate(
    db: CurrentSessionTransaction, request: Request, obj: CreateReplyCandidateParam
) -> ResponseSchemaModel[GetReplyCandidateDetail]:
    data = await approval_service.create_candidate(db=db, request=request, obj=obj)
    return response_base.success(data=data)

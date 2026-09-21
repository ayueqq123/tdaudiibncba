from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.app.tg.schema.runtime_command import (
    AckRuntimeCommandParam,
    CreateRuntimeCommandParam,
    GetRuntimeCommandDetail,
)
from backend.app.tg.service.command_service import runtime_command_service
from backend.app.tg.service.rule_service import clone_rule_service
from backend.common.response.response_schema import (
    ResponseSchemaModel,
    response_base,
)
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction

router = APIRouter()

# ---------- Worker 拉取侧(运行面) ----------


@router.get(
    '/accounts/{account_id}/rules',
    summary='Worker 拉取账号已发布规则快照',
    dependencies=[DependsJwtAuth],
)
async def pull_rules(
    db: CurrentSession,
    request: Request,
    account_id: Annotated[int, Path(description='账号 ID')],
) -> ResponseSchemaModel[list[dict]]:
    rules = await clone_rule_service.get_all(db=db, request=request)
    out: list[dict] = []
    for r in rules:
        if r.account_id != account_id or r.status != 'published' or not r.enabled:
            continue
        ver = await clone_rule_service.get_versions(db=db, request=request, pk=r.id)
        cur = next((v for v in ver if v.version == r.current_version), None)
        if cur:
            out.append({'rule_id': r.id, 'version': cur.version, 'snapshot': cur.snapshot})
    return response_base.success(data=out)


@router.get(
    '/accounts/{account_id}/commands',
    summary='Worker 拉取待执行命令',
    dependencies=[DependsJwtAuth],
)
async def pull_commands(
    db: CurrentSession,
    request: Request,
    account_id: Annotated[int, Path(description='账号 ID')],
) -> ResponseSchemaModel[list[GetRuntimeCommandDetail]]:
    data = await runtime_command_service.get_pending(db=db, account_id=account_id)
    return response_base.success(data=data)


@router.post(
    '/commands/{command_id}/ack',
    summary='Worker 命令回执',
    dependencies=[DependsJwtAuth],
)
async def ack_command(
    db: CurrentSessionTransaction,
    command_id: Annotated[int, Path(description='命令 ID')],
    obj: AckRuntimeCommandParam,
) -> ResponseSchemaModel[GetRuntimeCommandDetail]:
    data = await runtime_command_service.ack(db=db, command_id=command_id, obj=obj)
    return response_base.success(data=data)


# ---------- 管理面 ----------


@router.post(
    '/accounts/{account_id}/commands',
    summary='下发运行时命令',
    dependencies=[Depends(RequestPermission('tg:command:issue')), DependsRBAC],
)
async def issue_command(
    db: CurrentSessionTransaction,
    request: Request,
    account_id: Annotated[int, Path(description='账号 ID')],
    obj: CreateRuntimeCommandParam,
) -> ResponseSchemaModel[GetRuntimeCommandDetail]:
    data = await runtime_command_service.issue(db=db, request=request, account_id=account_id, obj=obj)
    return response_base.success(data=data)


@router.get('/commands', summary='命令列表', dependencies=[DependsJwtAuth])
async def get_commands(
    db: CurrentSession,
    request: Request,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
    account_id: Annotated[int | None, Query(description='账号 ID')] = None,
    status: Annotated[str | None, Query(description='状态')] = None,
) -> ResponseSchemaModel[list[GetRuntimeCommandDetail]]:
    data = await runtime_command_service.get_all(
        db=db,
        request=request,
        tenant_id=tenant_id,
        project_id=project_id,
        account_id=account_id,
        status=status,
    )
    return response_base.success(data=data)

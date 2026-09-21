from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from backend.app.tg.schema.tenant import CreateTenantParam, GetTenantDetail, UpdateTenantParam
from backend.app.tg.service.tenant_service import tenant_service
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction

router = APIRouter()


@router.get('/{pk}', summary='获取租户详情', dependencies=[DependsJwtAuth])
async def get_tenant(
    db: CurrentSession, pk: Annotated[int, Path(description='租户 ID')]
) -> ResponseSchemaModel[GetTenantDetail]:
    data = await tenant_service.get(db=db, pk=pk)
    return response_base.success(data=data)


@router.get('', summary='获取租户列表', dependencies=[DependsJwtAuth])
async def get_tenants(
    db: CurrentSession,
    name: Annotated[str | None, Query(description='租户名称')] = None,
    status: Annotated[int | None, Query(description='状态')] = None,
) -> ResponseSchemaModel[list[GetTenantDetail]]:
    data = await tenant_service.get_all(db=db, name=name, status=status)
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建租户',
    dependencies=[Depends(RequestPermission('tg:tenant:add')), DependsRBAC],
)
async def create_tenant(db: CurrentSessionTransaction, obj: CreateTenantParam) -> ResponseModel:
    await tenant_service.create(db=db, obj=obj)
    return response_base.success()


@router.put(
    '/{pk}',
    summary='更新租户',
    dependencies=[Depends(RequestPermission('tg:tenant:edit')), DependsRBAC],
)
async def update_tenant(
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='租户 ID')],
    obj: UpdateTenantParam,
) -> ResponseModel:
    count = await tenant_service.update(db=db, pk=pk, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}',
    summary='删除租户',
    dependencies=[Depends(RequestPermission('tg:tenant:del')), DependsRBAC],
)
async def delete_tenant(
    db: CurrentSessionTransaction, pk: Annotated[int, Path(description='租户 ID')]
) -> ResponseModel:
    count = await tenant_service.delete(db=db, pk=pk)
    if count > 0:
        return response_base.success()
    return response_base.fail()

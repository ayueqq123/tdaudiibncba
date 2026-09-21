from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from backend.app.tg.schema.membership import (
    CreateMembershipParam,
    GetMembershipDetail,
    UpdateMembershipParam,
)
from backend.app.tg.service.membership_service import membership_service
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction

router = APIRouter()


@router.get('/{pk}', summary='获取成员详情', dependencies=[DependsJwtAuth])
async def get_membership(
    db: CurrentSession, pk: Annotated[int, Path(description='成员 ID')]
) -> ResponseSchemaModel[GetMembershipDetail]:
    data = await membership_service.get(db=db, pk=pk)
    return response_base.success(data=data)


@router.get('', summary='获取成员列表', dependencies=[DependsJwtAuth])
async def get_memberships(
    db: CurrentSession,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
    user_id: Annotated[int | None, Query(description='系统用户 ID')] = None,
) -> ResponseSchemaModel[list[GetMembershipDetail]]:
    data = await membership_service.get_all(db=db, tenant_id=tenant_id, project_id=project_id, user_id=user_id)
    return response_base.success(data=data)


@router.post(
    '',
    summary='添加项目成员',
    dependencies=[Depends(RequestPermission('tg:membership:add')), DependsRBAC],
)
async def create_membership(db: CurrentSessionTransaction, obj: CreateMembershipParam) -> ResponseModel:
    await membership_service.create(db=db, obj=obj)
    return response_base.success()


@router.put(
    '/{pk}',
    summary='更新成员角色',
    dependencies=[Depends(RequestPermission('tg:membership:edit')), DependsRBAC],
)
async def update_membership(
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='成员 ID')],
    obj: UpdateMembershipParam,
) -> ResponseModel:
    count = await membership_service.update(db=db, pk=pk, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}',
    summary='移除项目成员',
    dependencies=[Depends(RequestPermission('tg:membership:del')), DependsRBAC],
)
async def delete_membership(
    db: CurrentSessionTransaction, pk: Annotated[int, Path(description='成员 ID')]
) -> ResponseModel:
    count = await membership_service.delete(db=db, pk=pk)
    if count > 0:
        return response_base.success()
    return response_base.fail()

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from backend.app.tg.schema.project import CreateProjectParam, GetProjectDetail, UpdateProjectParam
from backend.app.tg.service.project_service import project_service
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction

router = APIRouter()


@router.get('/{pk}', summary='获取项目详情', dependencies=[DependsJwtAuth])
async def get_project(
    db: CurrentSession, pk: Annotated[int, Path(description='项目 ID')]
) -> ResponseSchemaModel[GetProjectDetail]:
    data = await project_service.get(db=db, pk=pk)
    return response_base.success(data=data)


@router.get('', summary='获取项目列表', dependencies=[DependsJwtAuth])
async def get_projects(
    db: CurrentSession,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    name: Annotated[str | None, Query(description='项目名称')] = None,
    status: Annotated[int | None, Query(description='状态')] = None,
) -> ResponseSchemaModel[list[GetProjectDetail]]:
    data = await project_service.get_all(db=db, tenant_id=tenant_id, name=name, status=status)
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建项目',
    dependencies=[Depends(RequestPermission('tg:project:add')), DependsRBAC],
)
async def create_project(db: CurrentSessionTransaction, obj: CreateProjectParam) -> ResponseModel:
    await project_service.create(db=db, obj=obj)
    return response_base.success()


@router.put(
    '/{pk}',
    summary='更新项目',
    dependencies=[Depends(RequestPermission('tg:project:edit')), DependsRBAC],
)
async def update_project(
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='项目 ID')],
    obj: UpdateProjectParam,
) -> ResponseModel:
    count = await project_service.update(db=db, pk=pk, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}',
    summary='删除项目',
    dependencies=[Depends(RequestPermission('tg:project:del')), DependsRBAC],
)
async def delete_project(
    db: CurrentSessionTransaction, pk: Annotated[int, Path(description='项目 ID')]
) -> ResponseModel:
    count = await project_service.delete(db=db, pk=pk)
    if count > 0:
        return response_base.success()
    return response_base.fail()

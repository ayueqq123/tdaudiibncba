from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.app.tg.schema.clone_rule import (
    CloneTargetParam,
    CreateCloneRuleParam,
    GetCloneRuleDetail,
    GetCloneRuleVersionDetail,
    PublishCloneRuleParam,
    UpdateCloneRuleParam,
)
from backend.app.tg.service.rule_service import clone_rule_service
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


@router.get('/{pk}', summary='获取规则详情(含目标)', dependencies=[DependsJwtAuth])
async def get_rule(
    db: CurrentSession, request: Request, pk: Annotated[int, Path(description='规则 ID')]
) -> ResponseSchemaModel[GetCloneRuleDetail]:
    data = await clone_rule_service.get_with_targets(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.get('', summary='获取规则列表', dependencies=[DependsJwtAuth])
async def get_rules(
    db: CurrentSession,
    request: Request,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
) -> ResponseSchemaModel[list[GetCloneRuleDetail]]:
    data = await clone_rule_service.get_all(db=db, request=request, tenant_id=tenant_id, project_id=project_id)
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建 Clone 规则',
    dependencies=[Depends(RequestPermission('tg:rule:add')), DependsRBAC],
)
async def create_rule(db: CurrentSessionTransaction, request: Request, obj: CreateCloneRuleParam) -> ResponseModel:
    await clone_rule_service.create(db=db, request=request, obj=obj)
    return response_base.success()


@router.put(
    '/{pk}',
    summary='更新规则草稿',
    dependencies=[Depends(RequestPermission('tg:rule:edit')), DependsRBAC],
)
async def update_rule(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='规则 ID')],
    obj: UpdateCloneRuleParam,
) -> ResponseModel:
    count = await clone_rule_service.update(db=db, request=request, pk=pk, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.post(
    '/{pk}/targets',
    summary='添加规则目标',
    dependencies=[Depends(RequestPermission('tg:rule:edit')), DependsRBAC],
)
async def add_target(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='规则 ID')],
    obj: CloneTargetParam,
) -> ResponseModel:
    await clone_rule_service.add_target(db=db, request=request, rule_id=pk, obj=obj)
    return response_base.success()


@router.put(
    '/{pk}/targets/{target_id}',
    summary='修改规则目标',
    dependencies=[Depends(RequestPermission('tg:rule:edit')), DependsRBAC],
)
async def update_target(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='规则 ID')],
    target_id: Annotated[int, Path(description='目标 ID')],
    obj: CloneTargetParam,
) -> ResponseModel:
    await clone_rule_service.update_target(db=db, request=request, rule_id=pk, target_id=target_id, obj=obj)
    return response_base.success()


@router.delete(
    '/{pk}/targets/{target_id}',
    summary='退役规则目标',
    dependencies=[Depends(RequestPermission('tg:rule:edit')), DependsRBAC],
)
async def retire_target(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='规则 ID')],
    target_id: Annotated[int, Path(description='目标 ID')],
) -> ResponseModel:
    count = await clone_rule_service.retire_target(db=db, request=request, rule_id=pk, target_id=target_id)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.post(
    '/{pk}/dry-run',
    summary='规则 dry-run 预览(无 Telegram 副作用)',
    dependencies=[DependsJwtAuth],
)
async def dry_run(
    db: CurrentSession, request: Request, pk: Annotated[int, Path(description='规则 ID')]
) -> ResponseSchemaModel[dict]:
    data = await clone_rule_service.dry_run(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.post(
    '/{pk}/publish',
    summary='发布规则(生成不可变快照)',
    dependencies=[Depends(RequestPermission('tg:rule:publish')), DependsRBAC],
)
async def publish(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='规则 ID')],
    obj: PublishCloneRuleParam,
) -> ResponseSchemaModel[GetCloneRuleVersionDetail]:
    data = await clone_rule_service.publish(db=db, request=request, pk=pk, expected_version=obj.expected_version)
    return response_base.success(data=data)


@router.get('/{pk}/versions', summary='获取规则版本历史', dependencies=[DependsJwtAuth])
async def get_versions(
    db: CurrentSession, request: Request, pk: Annotated[int, Path(description='规则 ID')]
) -> ResponseSchemaModel[list[GetCloneRuleVersionDetail]]:
    data = await clone_rule_service.get_versions(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.delete(
    '/{pk}',
    summary='删除规则',
    dependencies=[Depends(RequestPermission('tg:rule:del')), DependsRBAC],
)
async def delete_rule(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='规则 ID')],
) -> ResponseModel:
    count = await clone_rule_service.delete(db=db, request=request, pk=pk)
    if count > 0:
        return response_base.success()
    return response_base.fail()

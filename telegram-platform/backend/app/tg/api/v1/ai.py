from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.app.tg.crud.crud_ai import ai_binding_dao, ai_conversation_dao, ai_run_dao
from backend.app.tg.schema.ai import (
    AiTriggerParam,
    CreateAiBindingParam,
    GetAiBindingDetail,
    GetAiConversationDetail,
    GetAiRunDetail,
    SetAutoApproveParam,
    UpdateAiBindingParam,
)
from backend.app.tg.service.ai_service import ai_service
from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction

router = APIRouter()


@router.get('/bindings', summary='AI 绑定列表', dependencies=[DependsJwtAuth])
async def get_bindings(
    db: CurrentSession,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
) -> ResponseSchemaModel[list[GetAiBindingDetail]]:
    data = await ai_binding_dao.get_all(db, tenant_id=tenant_id, project_id=project_id)
    return response_base.success(data=data)


@router.post(
    '/bindings',
    summary='注册 AI 绑定',
    dependencies=[Depends(RequestPermission('tg:ai:binding:edit')), DependsRBAC],
)
async def create_binding(
    db: CurrentSessionTransaction, obj: CreateAiBindingParam
) -> ResponseSchemaModel[GetAiBindingDetail]:
    binding = await ai_service.create_binding(db=db, obj=obj)
    return response_base.success(data=binding)


@router.put(
    '/bindings/{pk}',
    summary='更新 AI 绑定',
    dependencies=[Depends(RequestPermission('tg:ai:binding:edit')), DependsRBAC],
)
async def update_binding(
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='绑定 ID')],
    obj: UpdateAiBindingParam,
) -> ResponseSchemaModel[GetAiBindingDetail]:
    binding = await ai_service.update_binding(db=db, pk=pk, obj=obj)
    return response_base.success(data=binding)


@router.put(
    '/auto-approve',
    summary='批量开关自动审批(项目内所有 openai 绑定)',
    dependencies=[Depends(RequestPermission('tg:ai:binding:edit')), DependsRBAC],
)
async def set_auto_approve(
    db: CurrentSessionTransaction, obj: SetAutoApproveParam
) -> ResponseSchemaModel[dict]:
    bindings = await ai_binding_dao.get_all(db, tenant_id=obj.tenant_id, project_id=obj.project_id)
    n = 0
    for b in bindings:
        if b.engine == 'openai' and b.auto_approve != obj.enabled:
            await ai_binding_dao.update_fields(db, b.id, {'auto_approve': obj.enabled})
            n += 1
    return response_base.success(data={'updated': n, 'enabled': obj.enabled})


@router.delete(
    '/bindings/{pk}',
    summary='删除 AI 绑定',
    dependencies=[Depends(RequestPermission('tg:ai:binding:edit')), DependsRBAC],
)
async def delete_binding(
    db: CurrentSessionTransaction, pk: Annotated[int, Path(description='绑定 ID')]
) -> ResponseSchemaModel[int]:
    n = await ai_service.delete_binding(db=db, pk=pk)
    return response_base.success(data=n)


@router.get('/conversations', summary='AI 会话列表', dependencies=[DependsJwtAuth])
async def get_conversations(
    db: CurrentSession,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
) -> ResponseSchemaModel[list[GetAiConversationDetail]]:
    data = await ai_conversation_dao.get_all(db, tenant_id=tenant_id, project_id=project_id)
    return response_base.success(data=data)


@router.get('/runs', summary='AI 运行列表', dependencies=[DependsJwtAuth])
async def get_runs(
    db: CurrentSession,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
    status: Annotated[str | None, Query(description='run 状态')] = None,
) -> ResponseSchemaModel[list[GetAiRunDetail]]:
    data = await ai_run_dao.get_all(db, tenant_id=tenant_id, project_id=project_id, status=status)
    return response_base.success(data=data)


@router.post(
    '/runs/trigger',
    summary='手动触发 AI 生成(测试/演示)',
    dependencies=[Depends(RequestPermission('tg:ai:run:trigger')), DependsRBAC],
)
async def trigger_run(
    db: CurrentSessionTransaction, obj: AiTriggerParam
) -> ResponseSchemaModel[GetAiRunDetail]:
    run = await ai_service.trigger(db=db, obj=obj)
    return response_base.success(data=run)


@router.post(
    '/runs/{pk}/cancel',
    summary='平台侧取消 AI 运行',
    dependencies=[Depends(RequestPermission('tg:ai:run:cancel')), DependsRBAC],
)
async def cancel_run(
    db: CurrentSessionTransaction, pk: Annotated[int, Path(description='run ID')]
) -> ResponseSchemaModel[GetAiRunDetail]:
    run = await ai_service.cancel_run(db=db, pk=pk)
    return response_base.success(data=run)


# LangBot 回调:HMAC 验签替代 JWT,binding 决定租户(§9.5)
callback_router = APIRouter()


@callback_router.post(
    '/internal/ai/langbot/{binding_uuid}/callback',
    summary='LangBot 签名回调入口',
)
async def langbot_callback(
    db: CurrentSessionTransaction,
    request: Request,
    binding_uuid: Annotated[str, Path(description='绑定 uuid')],
) -> dict:
    raw = await request.body()
    result = await ai_service.handle_callback(
        db=db, binding_uuid=binding_uuid, raw_body=raw, headers=dict(request.headers)
    )
    return {'code': 0, 'result': result}

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.app.tg.crud.crud_ai import ai_binding_dao, ai_conversation_dao, ai_run_dao
from backend.app.tg.schema.ai import (
    AiMemberParam,
    AiPersonaParam,
    AiPrivateReplyParam,
    AiScriptParam,
    AiTriggerParam,
    CreateAiBindingParam,
    CreateAiGroupParam,
    GetAiBindingDetail,
    GetAiConversationDetail,
    GetAiGroupDetail,
    GetAiGroupRunDetail,
    GetAiMemberDetail,
    GetAiPersonaDetail,
    GetAiPrivateReplyDetail,
    GetAiRunDetail,
    GetAiScriptDetail,
    SetAutoApproveParam,
    UpdateAiBindingParam,
    UpdateAiGroupParam,
)
from backend.app.tg.service.ai_group_service import ai_group_service
from backend.app.tg.service.ai_service import AiService, ai_service
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
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
async def set_auto_approve(db: CurrentSessionTransaction, obj: SetAutoApproveParam) -> ResponseSchemaModel[dict]:
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
async def trigger_run(db: CurrentSessionTransaction, obj: AiTriggerParam) -> ResponseSchemaModel[GetAiRunDetail]:
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


# ---- 炒群任务(按群):群 → 成员(账号 + 人设)→ 剧本 ----
EDIT = [Depends(RequestPermission('tg:ai:binding:edit')), DependsRBAC]
GroupId = Annotated[int, Path(description='炒群任务 ID')]


@router.get('/groups', summary='炒群任务列表', dependencies=[DependsJwtAuth])
async def get_groups(
    db: CurrentSession,
    request: Request,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
) -> ResponseSchemaModel[list[GetAiGroupDetail]]:
    data = await ai_group_service.list_groups(db=db, request=request, tenant_id=tenant_id, project_id=project_id)
    return response_base.success(data=data)


@router.post('/groups', summary='新建炒群任务', dependencies=EDIT)
async def create_group(
    db: CurrentSessionTransaction, request: Request, obj: CreateAiGroupParam
) -> ResponseSchemaModel[GetAiGroupDetail]:
    return response_base.success(data=await ai_group_service.create_group(db=db, request=request, obj=obj))


@router.put('/groups/{pk}', summary='更新炒群任务', dependencies=EDIT)
async def update_group(
    db: CurrentSessionTransaction, request: Request, pk: GroupId, obj: UpdateAiGroupParam
) -> ResponseSchemaModel[GetAiGroupDetail]:
    return response_base.success(data=await ai_group_service.update_group(db=db, request=request, pk=pk, obj=obj))


@router.delete('/groups/{pk}', summary='删除炒群任务(连同成员/剧本)', dependencies=EDIT)
async def delete_group(db: CurrentSessionTransaction, request: Request, pk: GroupId) -> ResponseModel:
    await ai_group_service.delete_group(db=db, request=request, pk=pk)
    return response_base.success()


@router.get('/groups/{pk}/messages', summary='群实时消息缓存', dependencies=[DependsJwtAuth])
async def get_group_messages(db: CurrentSession, request: Request, pk: GroupId) -> ResponseSchemaModel[list[dict]]:
    group = await ai_group_service.get_group(db, request, pk)
    return response_base.success(data=list(group.recent_messages or [])[-100:])


@router.get('/groups/{pk}/runs', summary='发言记录', dependencies=[DependsJwtAuth])
async def get_group_runs(
    db: CurrentSession, request: Request, pk: GroupId
) -> ResponseSchemaModel[list[GetAiGroupRunDetail]]:
    return response_base.success(data=await ai_group_service.group_runs(db=db, request=request, pk=pk))


@router.post('/groups/{pk}/warmup', summary='立即暖场一次', dependencies=EDIT)
async def warmup_group(db: CurrentSessionTransaction, request: Request, pk: GroupId) -> ResponseSchemaModel[dict]:
    ok = await ai_group_service.warmup_now(db=db, request=request, pk=pk)
    return response_base.success(data={'started': ok})


@router.get('/groups/{pk}/members', summary='成员列表', dependencies=[DependsJwtAuth])
async def get_members(
    db: CurrentSession, request: Request, pk: GroupId
) -> ResponseSchemaModel[list[GetAiMemberDetail]]:
    return response_base.success(data=await ai_group_service.list_members(db=db, request=request, pk=pk))


@router.post('/groups/{pk}/members', summary='添加成员(会自动进群)', dependencies=EDIT)
async def add_member(db: CurrentSessionTransaction, request: Request, pk: GroupId, obj: AiMemberParam) -> ResponseModel:
    await ai_group_service.add_member(db=db, request=request, pk=pk, obj=obj)
    return response_base.success()


@router.put('/groups/{pk}/members/{member_id}', summary='更新成员人设/参数', dependencies=EDIT)
async def update_member(
    db: CurrentSessionTransaction, request: Request, pk: GroupId, member_id: int, obj: AiMemberParam
) -> ResponseModel:
    await ai_group_service.update_member(db=db, request=request, pk=pk, member_id=member_id, obj=obj)
    return response_base.success()


@router.delete('/groups/{pk}/members/{member_id}', summary='移除成员', dependencies=EDIT)
async def delete_member(db: CurrentSessionTransaction, request: Request, pk: GroupId, member_id: int) -> ResponseModel:
    await ai_group_service.delete_member(db=db, request=request, pk=pk, member_id=member_id)
    return response_base.success()


@router.get('/groups/{pk}/scripts', summary='剧本列表', dependencies=[DependsJwtAuth])
async def get_scripts(
    db: CurrentSession, request: Request, pk: GroupId
) -> ResponseSchemaModel[list[GetAiScriptDetail]]:
    return response_base.success(data=await ai_group_service.list_scripts(db=db, request=request, pk=pk))


@router.post('/groups/{pk}/scripts', summary='新建剧本', dependencies=EDIT)
async def create_script(
    db: CurrentSessionTransaction, request: Request, pk: GroupId, obj: AiScriptParam
) -> ResponseSchemaModel[GetAiScriptDetail]:
    return response_base.success(data=await ai_group_service.save_script(db=db, request=request, pk=pk, obj=obj))


@router.put('/groups/{pk}/scripts/{script_id}', summary='修改剧本', dependencies=EDIT)
async def update_script(
    db: CurrentSessionTransaction, request: Request, pk: GroupId, script_id: int, obj: AiScriptParam
) -> ResponseSchemaModel[GetAiScriptDetail]:
    data = await ai_group_service.save_script(db=db, request=request, pk=pk, obj=obj, script_id=script_id)
    return response_base.success(data=data)


@router.delete('/groups/{pk}/scripts/{script_id}', summary='删除剧本', dependencies=EDIT)
async def delete_script(db: CurrentSessionTransaction, request: Request, pk: GroupId, script_id: int) -> ResponseModel:
    await ai_group_service.delete_script(db=db, request=request, pk=pk, script_id=script_id)
    return response_base.success()


@router.post('/groups/{pk}/scripts/{script_id}/start', summary='播放剧本', dependencies=EDIT)
async def start_script(db: CurrentSessionTransaction, request: Request, pk: GroupId, script_id: int) -> ResponseModel:
    token = await ai_group_service.start_script(db=db, request=request, pk=pk, script_id=script_id)
    await db.commit()
    AiService._dispatch_script(script_id, token, 1)
    return response_base.success()


@router.post('/groups/{pk}/scripts/{script_id}/stop', summary='停止剧本', dependencies=EDIT)
async def stop_script(db: CurrentSessionTransaction, request: Request, pk: GroupId, script_id: int) -> ResponseModel:
    await ai_group_service.stop_script(db=db, request=request, pk=pk, script_id=script_id)
    return response_base.success()


@router.get('/personas', summary='人设模板列表', dependencies=[DependsJwtAuth])
async def get_personas(
    db: CurrentSession,
    request: Request,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
) -> ResponseSchemaModel[list[GetAiPersonaDetail]]:
    data = await ai_group_service.list_personas(db=db, request=request, tenant_id=tenant_id, project_id=project_id)
    return response_base.success(data=data)


@router.post('/personas', summary='保存人设模板', dependencies=EDIT)
async def create_persona(
    db: CurrentSessionTransaction, request: Request, obj: AiPersonaParam
) -> ResponseSchemaModel[GetAiPersonaDetail]:
    return response_base.success(data=await ai_group_service.save_persona(db=db, request=request, obj=obj))


@router.put('/personas/{pk}', summary='修改人设模板', dependencies=EDIT)
async def update_persona(
    db: CurrentSessionTransaction, request: Request, pk: int, obj: AiPersonaParam
) -> ResponseSchemaModel[GetAiPersonaDetail]:
    return response_base.success(data=await ai_group_service.save_persona(db=db, request=request, obj=obj, pk=pk))


@router.delete('/personas/{pk}', summary='删除人设模板', dependencies=EDIT)
async def delete_persona(db: CurrentSessionTransaction, request: Request, pk: int) -> ResponseModel:
    await ai_group_service.delete_persona(db=db, request=request, pk=pk)
    return response_base.success()


@router.get('/private-replies', summary='私信自动回复配置', dependencies=[DependsJwtAuth])
async def get_private_replies(
    db: CurrentSession,
    request: Request,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
) -> ResponseSchemaModel[list[GetAiPrivateReplyDetail]]:
    data = await ai_group_service.list_private(db=db, request=request, tenant_id=tenant_id, project_id=project_id)
    return response_base.success(data=data)


@router.put('/private-replies/{account_id}', summary='保存账号私信自动回复', dependencies=EDIT)
async def save_private_reply(
    db: CurrentSessionTransaction, request: Request, account_id: int, obj: AiPrivateReplyParam
) -> ResponseSchemaModel[GetAiPrivateReplyDetail]:
    data = await ai_group_service.save_private(db=db, request=request, account_id=account_id, obj=obj)
    return response_base.success(data=data)

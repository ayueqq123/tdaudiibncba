import base64
import json
import os
import secrets

from typing import Annotated

import anyio

from fastapi import APIRouter, Depends, Path, Query, Request
from starlette.authentication import UnauthenticatedUser

from backend.app.tg.crud.crud_approval import reply_candidate_dao
from backend.app.tg.crud.crud_clone_rule import clone_rule_dao, clone_rule_version_dao
from backend.app.tg.crud.crud_project import project_dao
from backend.app.tg.crud.crud_telegram_account import telegram_account_dao
from backend.app.tg.crud.crud_tenant import tenant_dao
from backend.app.tg.schema.ai import AiGroupEventParam
from backend.app.tg.schema.runtime_command import (
    AckRuntimeCommandParam,
    ReportAccountStatusParam,
    CreateRuntimeCommandParam,
    GetRuntimeCommandDetail,
)
from backend.app.tg.service.ai_service import ai_service
from backend.app.tg.service.command_service import runtime_command_service
from backend.common.exception import errors
from backend.utils.timezone import timezone
from backend.common.response.response_schema import (
    ResponseSchemaModel,
    response_base,
)
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.core.conf import settings
from backend.database.db import CurrentSession, CurrentSessionTransaction

router = APIRouter()

# ---------- Worker 拉取侧(运行面) ----------


def _worker_or_jwt(request: Request) -> None:
    """Worker 服务凭证(X-Worker-Token)或用户 JWT 二选一。

    Worker 不持有用户态 JWT;凭证为空或未配置时回退 JWT 路径。"""
    token = request.headers.get('x-worker-token')
    if token is not None:
        expected = settings.RUNTIME_WORKER_TOKEN
        if not expected or not secrets.compare_digest(token, expected):
            raise errors.TokenError(msg='Worker token 无效')
        return
    if isinstance(request.user, UnauthenticatedUser):
        raise errors.TokenError


DependsWorkerAuth = Depends(_worker_or_jwt)


@router.get('/accounts', summary='Worker 拉取期望运行账号清单', dependencies=[DependsWorkerAuth])
async def pull_running_accounts(
    db: CurrentSession,
) -> ResponseSchemaModel[list[dict]]:
    """租约分配视图:返回 desired_status='running' 的账号。Worker 以 uuid 为账号键。"""
    rows = await telegram_account_dao.get_running(db)
    out = []
    for r in rows:
        tenant = await tenant_dao.get(db, r.tenant_id)
        project = await project_dao.get(db, r.project_id)
        if tenant is None or project is None:
            continue  # 范围实体缺失的账号不下发,worker 侧无从落 tenant_uuid
        out.append({
            'id': r.id,
            'uuid': r.uuid,
            'tenant_id': r.tenant_id,
            'project_id': r.project_id,
            'tenant_uuid': tenant.uuid,
            'project_uuid': project.uuid,
            'telegram_user_id': r.telegram_user_id,
            'observed_status': r.observed_status,
            'has_session': r.secret_ref is not None,
        })
    return response_base.success(data=out)


@router.get(
    '/accounts/{account_uuid}/session',
    summary='Worker 拉取账号会话材料',
    dependencies=[DependsWorkerAuth],
)
async def pull_session(
    db: CurrentSession,
    account_uuid: Annotated[str, Path(description='账号 UUID')],
) -> ResponseSchemaModel[dict]:
    """会话字节经运行面内网传输(base64);暂存目录只挂控制面,worker 不落共享卷。"""
    account = await telegram_account_dao.get_by_uuid(db, account_uuid)
    if account is None or account.secret_ref is None:
        raise errors.NotFoundError(msg='账号或会话材料不存在')
    if account.desired_status != 'running':
        raise errors.RequestError(msg='账号未处于运行期望态')
    # realpath 解析符号链接,确保 secret_ref 不能逃出导入存储目录
    base = await anyio.Path(settings.TG_IMPORT_STORAGE_DIR).resolve()
    session_path = await anyio.Path(
        os.path.join(str(base), account.secret_ref)).resolve()
    if os.path.commonpath([str(base), str(session_path)]) != str(base):
        raise errors.RequestError(msg='非法会话引用')
    if not await session_path.is_file():
        raise errors.NotFoundError(msg='会话文件缺失')
    meta: dict = {}
    meta_path = session_path.with_suffix('.json')
    if await meta_path.is_file():
        try:
            meta = json.loads(await meta_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            meta = {}
    return response_base.success(
        data={
            'uuid': account.uuid,
            'session_b64': base64.b64encode(await session_path.read_bytes()).decode(),
            'meta': {
                'app_id': meta.get('app_id'),
                'app_hash': meta.get('app_hash'),
                'device': meta.get('device'),
                'app_version': meta.get('app_version'),
            },
        }
    )


@router.get(
    '/candidates/{candidate_uuid}',
    summary='Worker 拉取回复候选正文(payload_ref 解析)',
    dependencies=[DependsWorkerAuth],
)
async def pull_candidate(
    db: CurrentSession,
    candidate_uuid: Annotated[str, Path(description='候选 UUID')],
) -> ResponseSchemaModel[dict]:
    """delivery_job.payload_ref='candidate:{uuid}' 的正文解析端点。"""
    cand = await reply_candidate_dao.get_by_uuid(db, candidate_uuid)
    if cand is None:
        raise errors.NotFoundError(msg='候选不存在')
    return response_base.success(
        data={
            'uuid': cand.uuid,
            'content': cand.content,
            'content_hash': cand.content_hash,
            'expires_at': cand.expires_at,
            'target_chat_id': cand.target_chat_id,
            'target_topic_id': cand.target_topic_id,
            'reply_to_source_id': cand.reply_to_source_id,
            'status': cand.status,
        }
    )


@router.get(
    '/accounts/{account_id}/rules',
    summary='Worker 拉取账号已发布规则快照',
    dependencies=[DependsWorkerAuth],
)
async def pull_rules(
    db: CurrentSession,
    account_id: Annotated[int, Path(description='账号 ID')],
) -> ResponseSchemaModel[list[dict]]:
    # Worker 凭证无 request.user —— 不走 request 作用域 service,直接查 dao;
    # 运行面本来就是部署内全局视图(§12)。
    rules = await clone_rule_dao.get_all(db)
    out: list[dict] = []
    for r in rules:
        if r.account_id != account_id or r.status != 'published' or not r.enabled:
            continue
        cur = await clone_rule_version_dao.get_by_rule_version(db, r.id, r.current_version)
        if cur:
            account = await telegram_account_dao.get_by_scope(
                db, r.tenant_id, r.project_id, r.account_id)
            out.append({
                'rule_id': r.id,
                'version': cur.version,
                'snapshot': cur.snapshot,
                # worker 侧以账号 uuid 为运行时键(租约/事件/投递均按 uuid 关联)
                'account_uuid': account.uuid if account else None,
            })
    return response_base.success(data=out)


@router.get(
    '/accounts/{account_id}/commands',
    summary='Worker 拉取待执行命令',
    dependencies=[DependsWorkerAuth],
)
async def pull_commands(
    db: CurrentSession,
    account_id: Annotated[int, Path(description='账号 ID')],
) -> ResponseSchemaModel[list[GetRuntimeCommandDetail]]:
    data = await runtime_command_service.get_pending(db=db, account_id=account_id)
    return response_base.success(data=data)


@router.post(
    '/ai/event',
    summary='Worker 上报群消息触发 AI 生成(炒群)',
    dependencies=[DependsWorkerAuth],
)
async def ai_group_event(
    db: CurrentSessionTransaction, obj: AiGroupEventParam
) -> ResponseSchemaModel[dict]:
    """openai 引擎绑定按 chat_id 匹配→逐绑定 trigger→生成→候选→审批。"""
    account = await telegram_account_dao.get(db, obj.api_row_id)
    if account is None:
        raise errors.NotFoundError(msg='账号不存在')
    n = await ai_service.handle_group_event(
        db=db, obj=obj, account=account, username=account.username
    )
    return response_base.success(data={'triggered': n})


@router.post(
    '/accounts/{api_row_id}/status',
    summary='Worker 上报账号观测状态',
    dependencies=[DependsWorkerAuth],
)
async def report_account_status(
    db: CurrentSessionTransaction,
    api_row_id: Annotated[int, Path(description='账号 API 行 ID')],
    obj: ReportAccountStatusParam,
) -> ResponseSchemaModel[dict]:
    account = await telegram_account_dao.get(db, api_row_id)
    if account is None:
        raise errors.NotFoundError(msg='账号不存在')
    await telegram_account_dao.update(
        db,
        api_row_id,
        {
            'observed_status': obj.observed_status,
            'last_error': obj.last_error,
            'last_seen_at': timezone.now(),
        },
    )
    return response_base.success(data={'ok': True})


@router.post(
    '/commands/{command_id}/ack',
    summary='Worker 命令回执',
    dependencies=[DependsWorkerAuth],
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

from fastapi import APIRouter

from backend.app.tg.api.v1.account import router as account_router
from backend.app.tg.api.v1.ai import callback_router as ai_callback_router
from backend.app.tg.api.v1.ai import router as ai_router
from backend.app.tg.api.v1.approval import router as approval_router
from backend.app.tg.api.v1.clone_rule import router as clone_rule_router
from backend.app.tg.api.v1.delivery import router as delivery_router
from backend.app.tg.api.v1.import_batch import router as import_batch_router
from backend.app.tg.api.v1.membership import router as membership_router
from backend.app.tg.api.v1.project import router as project_router
from backend.app.tg.api.v1.runtime import router as runtime_router
from backend.app.tg.api.v1.tenant import router as tenant_router
from backend.core.conf import settings

v1 = APIRouter(prefix=f'{settings.FASTAPI_API_V1_PATH}/tg')

v1.include_router(tenant_router, prefix='/tenants', tags=['TG 租户'])
v1.include_router(project_router, prefix='/projects', tags=['TG 项目'])
v1.include_router(membership_router, prefix='/memberships', tags=['TG 成员'])
v1.include_router(account_router, prefix='/accounts', tags=['TG 账号'])
v1.include_router(import_batch_router, prefix='/imports', tags=['TG 导入批次'])
v1.include_router(clone_rule_router, prefix='/clone-rules', tags=['TG Clone 规则'])
v1.include_router(runtime_router, prefix='/runtime', tags=['TG 运行时'])
v1.include_router(delivery_router, prefix='/deliveries', tags=['TG 投递'])
v1.include_router(approval_router, prefix='/approvals', tags=['TG 审批'])
v1.include_router(ai_router, prefix='/ai', tags=['TG AI'])
v1.include_router(ai_callback_router, tags=['TG AI 回调'])

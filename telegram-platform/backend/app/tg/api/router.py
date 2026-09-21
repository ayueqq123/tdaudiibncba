from fastapi import APIRouter

from backend.app.tg.api.v1.account import router as account_router
from backend.app.tg.api.v1.import_batch import router as import_batch_router
from backend.app.tg.api.v1.membership import router as membership_router
from backend.app.tg.api.v1.project import router as project_router
from backend.app.tg.api.v1.tenant import router as tenant_router
from backend.core.conf import settings

v1 = APIRouter(prefix=f'{settings.FASTAPI_API_V1_PATH}/tg')

v1.include_router(tenant_router, prefix='/tenants', tags=['TG 租户'])
v1.include_router(project_router, prefix='/projects', tags=['TG 项目'])
v1.include_router(membership_router, prefix='/memberships', tags=['TG 成员'])
v1.include_router(account_router, prefix='/accounts', tags=['TG 账号'])
v1.include_router(import_batch_router, prefix='/imports', tags=['TG 导入批次'])

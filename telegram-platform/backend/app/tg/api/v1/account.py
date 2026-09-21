from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, UploadFile

from backend.app.tg.schema.import_batch import GetImportBatchDetail
from backend.app.tg.schema.telegram_account import GetTgAccountDetail, UpdateTgAccountParam
from backend.app.tg.service.account_service import account_service
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction

router = APIRouter()


@router.get('/{pk}', summary='获取 Telegram 账号详情', dependencies=[DependsJwtAuth])
async def get_account(
    db: CurrentSession, request: Request, pk: Annotated[int, Path(description='账号 ID')]
) -> ResponseSchemaModel[GetTgAccountDetail]:
    data = await account_service.get(db=db, request=request, pk=pk)
    return response_base.success(data=data)


@router.get('', summary='获取 Telegram 账号列表', dependencies=[DependsJwtAuth])
async def get_accounts(
    db: CurrentSession,
    request: Request,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
    status: Annotated[str | None, Query(description='观测状态')] = None,
) -> ResponseSchemaModel[list[GetTgAccountDetail]]:
    data = await account_service.get_all(
        db=db, request=request, tenant_id=tenant_id, project_id=project_id, status=status
    )
    return response_base.success(data=data)


@router.put(
    '/{pk}',
    summary='更新 Telegram 账号(期望状态/备注)',
    dependencies=[Depends(RequestPermission('tg:account:edit')), DependsRBAC],
)
async def update_account(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='账号 ID')],
    obj: UpdateTgAccountParam,
) -> ResponseModel:
    count = await account_service.update(db=db, request=request, pk=pk, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}',
    summary='删除 Telegram 账号',
    dependencies=[Depends(RequestPermission('tg:account:del')), DependsRBAC],
)
async def delete_account(
    db: CurrentSessionTransaction,
    request: Request,
    pk: Annotated[int, Path(description='账号 ID')],
) -> ResponseModel:
    count = await account_service.delete(db=db, request=request, pk=pk)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.post(
    '/import',
    summary='批量导入 Session 包(zip)',
    description='上传 zip 后同步执行 runtime 验证(connect+getMe),验证通过的账号进入 imported_quarantine',
    dependencies=[Depends(RequestPermission('tg:account:import')), DependsRBAC],
)
async def import_accounts(
    db: CurrentSessionTransaction,
    request: Request,
    tenant_id: Annotated[int, Form(description='租户 ID')],
    project_id: Annotated[int, Form(description='项目 ID')],
    file: Annotated[UploadFile, File(description='session 包 zip')],
) -> ResponseSchemaModel[GetImportBatchDetail]:
    data = await account_service.import_zip(
        db=db, request=request, tenant_id=tenant_id, project_id=project_id, file=file
    )
    return response_base.success(data=data)

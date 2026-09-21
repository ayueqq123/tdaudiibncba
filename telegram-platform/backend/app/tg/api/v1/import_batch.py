from typing import Annotated

from fastapi import APIRouter, Path, Query, Request

from backend.app.tg.schema.import_batch import GetImportBatchDetail
from backend.app.tg.service.account_service import account_service
from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession

router = APIRouter()


@router.get('/{batch_id}', summary='获取导入批次详情(含逐项结果)', dependencies=[DependsJwtAuth])
async def get_import_batch(
    db: CurrentSession,
    request: Request,
    batch_id: Annotated[int, Path(description='批次 ID')],
) -> ResponseSchemaModel[GetImportBatchDetail]:
    data = await account_service.get_import(db=db, request=request, batch_id=batch_id)
    return response_base.success(data=data)


@router.get('', summary='获取导入批次列表', dependencies=[DependsJwtAuth])
async def get_import_batches(
    db: CurrentSession,
    request: Request,
    tenant_id: Annotated[int | None, Query(description='租户 ID')] = None,
    project_id: Annotated[int | None, Query(description='项目 ID')] = None,
) -> ResponseSchemaModel[list[GetImportBatchDetail]]:
    data = await account_service.get_imports(db=db, request=request, tenant_id=tenant_id, project_id=project_id)
    return response_base.success(data=data)

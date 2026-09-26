from fastapi import APIRouter, Request

from backend.app.tg.service.alert_service import alert_service
from backend.common.response.response_schema import ResponseModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession

router = APIRouter()


@router.get('', summary='异常告警列表', dependencies=[DependsJwtAuth])
async def get_alerts(db: CurrentSession, request: Request) -> ResponseModel:
    data = await alert_service.get_all(db=db, request=request)
    return response_base.success(data=data)

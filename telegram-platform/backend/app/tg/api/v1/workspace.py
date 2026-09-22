#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from pydantic import BaseModel, Field

from backend.app.admin.crud.crud_user import user_dao
from backend.app.tg.crud.crud_membership import membership_dao
from backend.app.tg.crud.crud_project import project_dao
from backend.app.tg.crud.crud_tenant import tenant_dao
from backend.app.tg.schema.membership import CreateMembershipParam
from backend.app.tg.schema.project import CreateProjectParam
from backend.app.tg.schema.tenant import CreateTenantParam
from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSessionTransaction

router = APIRouter()


class EnsureWorkspaceParam(BaseModel):
    """工作空间初始化参数"""

    user_id: int | None = Field(None, description='目标用户 ID,缺省为当前用户')


class WorkspaceDetail(BaseModel):
    """工作空间信息"""

    tenant_id: int = Field(description='租户 ID')
    project_id: int = Field(description='项目 ID')


@router.post('/ensure', summary='初始化用户工作空间', dependencies=[DependsJwtAuth])
async def ensure_workspace(
    db: CurrentSessionTransaction,
    request: Request,
    obj: Annotated[EnsureWorkspaceParam | None, Body()] = None,
) -> ResponseSchemaModel[WorkspaceDetail]:
    target_id = obj.user_id if obj and obj.user_id else request.user.id
    if target_id != request.user.id and not request.user.is_superuser:
        raise errors.ForbiddenError(msg='只能初始化自己的工作空间')
    user = await user_dao.get(db, target_id)
    if not user:
        raise errors.NotFoundError(msg='用户不存在')

    existing = await membership_dao.get_all(db, user_id=target_id)
    for m in existing:
        if m.role == 'owner':
            return response_base.success(data=WorkspaceDetail(tenant_id=m.tenant_id, project_id=m.project_id))
    if existing:
        m = existing[0]
        return response_base.success(data=WorkspaceDetail(tenant_id=m.tenant_id, project_id=m.project_id))

    tenant = await tenant_dao.create_model(
        db, CreateTenantParam(name=f'{user.username} 的空间', status=StatusType.enable)
    )
    project = await project_dao.create_model(
        db, CreateProjectParam(tenant_id=tenant.id, name='默认', status=StatusType.enable)
    )
    await membership_dao.create(
        db,
        CreateMembershipParam(
            tenant_id=tenant.id, project_id=project.id, user_id=target_id, role='owner', status=StatusType.enable
        ),
    )
    return response_base.success(data=WorkspaceDetail(tenant_id=tenant.id, project_id=project.id))

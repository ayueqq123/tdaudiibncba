from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field

from backend.common.enums import StatusType
from backend.common.schema import SchemaBase


class MembershipSchemaBase(SchemaBase):
    """成员基础模型"""

    tenant_id: int = Field(description='租户 ID')
    project_id: int = Field(description='项目 ID')
    user_id: int = Field(description='系统用户 ID')
    role: Literal['owner', 'admin', 'member'] = Field('member', description='成员角色')
    status: StatusType = Field(StatusType.enable, description='状态')


class CreateMembershipParam(MembershipSchemaBase):
    """创建成员参数"""


class UpdateMembershipParam(SchemaBase):
    """更新成员参数"""

    role: Literal['owner', 'admin', 'member'] = Field(description='成员角色')
    status: StatusType = Field(description='状态')


class GetMembershipDetail(MembershipSchemaBase):
    """成员详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='成员 ID')
    uuid: str = Field(description='成员 UUID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

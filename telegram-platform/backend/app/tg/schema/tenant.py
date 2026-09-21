from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.enums import StatusType
from backend.common.schema import SchemaBase


class TenantSchemaBase(SchemaBase):
    """租户基础模型"""

    name: str = Field(description='租户名称')
    status: StatusType = Field(description='状态')
    remark: str | None = Field(None, description='备注')


class CreateTenantParam(TenantSchemaBase):
    """创建租户参数"""


class UpdateTenantParam(TenantSchemaBase):
    """更新租户参数"""


class GetTenantDetail(TenantSchemaBase):
    """租户详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='租户 ID')
    uuid: str = Field(description='租户 UUID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

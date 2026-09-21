from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.enums import StatusType
from backend.common.schema import SchemaBase


class ProjectSchemaBase(SchemaBase):
    """项目基础模型"""

    tenant_id: int = Field(description='租户 ID')
    name: str = Field(description='项目名称')
    status: StatusType = Field(description='状态')
    remark: str | None = Field(None, description='备注')


class CreateProjectParam(ProjectSchemaBase):
    """创建项目参数"""


class UpdateProjectParam(ProjectSchemaBase):
    """更新项目参数"""


class GetProjectDetail(ProjectSchemaBase):
    """项目详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='项目 ID')
    uuid: str = Field(description='项目 UUID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

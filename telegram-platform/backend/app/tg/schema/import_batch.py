from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class CreateImportBatchParam(SchemaBase):
    """创建导入批次参数(service 内部使用)"""

    tenant_id: int
    project_id: int
    operator_id: int
    filename: str
    file_sha256: str


class GetImportBatchDetail(SchemaBase):
    """导入批次详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='批次 ID')
    uuid: str = Field(description='批次 UUID')
    tenant_id: int = Field(description='租户 ID')
    project_id: int = Field(description='项目 ID')
    operator_id: int = Field(description='操作者系统用户 ID')
    filename: str = Field(description='上传文件名')
    file_sha256: str = Field(description='文件 SHA-256')
    total: int = Field(description='session 总数')
    verified: int = Field(description='验证通过数')
    failed: int = Field(description='验证失败数')
    status: str = Field(description='批次状态')
    detail: list[dict[str, Any]] | None = Field(None, description='逐项结果')
    finished_at: datetime | None = Field(None, description='完成时间')
    created_time: datetime = Field(description='创建时间')

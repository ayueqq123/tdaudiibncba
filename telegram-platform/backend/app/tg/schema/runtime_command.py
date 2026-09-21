from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase

RuntimeCommandType = Literal[
    'StartAccount',
    'StopAccount',
    'ReloadConfig',
    'SyncChats',
    'ReconcileSource',
    'CancelJob',
]


class CreateRuntimeCommandParam(SchemaBase):
    """下发运行时命令参数"""

    type: RuntimeCommandType = Field(description='命令类型')
    payload: dict[str, Any] | None = Field(None, description='命令参数')
    expected_generation: int | None = Field(None, description='期望租约代次')
    dedup_key: str | None = Field(None, description='去重键(默认自动生成)')


class CreateRuntimeCommandInternalParam(SchemaBase):
    """落库参数(service 内部)"""

    tenant_id: int
    project_id: int
    account_id: int
    type: str
    issued_by: int
    payload: dict[str, Any] | None = None
    expected_generation: int | None = None
    dedup_key: str | None = None
    deadline: datetime | None = None
    trace_id: str | None = None


class AckRuntimeCommandParam(SchemaBase):
    """Worker 命令回执"""

    status: Literal['acknowledged', 'done', 'rejected'] = Field(description='回执状态')
    result: str | None = Field(None, description='执行结果摘要')


class GetRuntimeCommandDetail(SchemaBase):
    """运行时命令详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='命令 ID')
    uuid: str = Field(description='命令 UUID')
    dedup_key: str = Field(description='去重键')
    tenant_id: int = Field(description='租户 ID')
    project_id: int = Field(description='项目 ID')
    account_id: int = Field(description='账号 ID')
    type: str = Field(description='命令类型')
    payload: dict[str, Any] | None = Field(None, description='命令参数')
    expected_generation: int | None = Field(None, description='期望租约代次')
    deadline: datetime | None = Field(None, description='过期时间')
    trace_id: str | None = Field(None, description='链路 ID')
    status: str = Field(description='状态')
    result: str | None = Field(None, description='执行结果摘要')
    issued_by: int = Field(description='下发人')
    acked_at: datetime | None = Field(None, description='确认时间')
    finished_at: datetime | None = Field(None, description='完成时间')
    created_time: datetime = Field(description='创建时间')

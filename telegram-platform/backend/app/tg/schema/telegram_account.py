from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase

AccountStatus = Literal[
    'imported_quarantine',
    'verified',
    'active',
    'stopped',
    'reauth_required',
    'revoked',
    'disabled',
]


class TgTelegramAccountSchemaBase(SchemaBase):
    """Telegram 账号基础模型"""

    phone: str | None = Field(None, description='手机号')
    remark: str | None = Field(None, description='备注')


class CreateTgAccountParam(SchemaBase):
    """导入落库参数(service 内部使用,不对 API 暴露)"""

    tenant_id: int
    project_id: int
    import_batch_id: int | None = None
    phone: str | None = None
    telegram_user_id: int | None = None
    username: str | None = None
    secret_ref: str | None = None
    observed_status: str = 'imported_quarantine'
    last_error: str | None = None


class UpdateTgAccountParam(TgTelegramAccountSchemaBase):
    """更新 Telegram 账号参数"""

    desired_status: Literal['stopped', 'running'] = Field(description='期望状态')


class GetTgAccountDetail(TgTelegramAccountSchemaBase):
    """Telegram 账号详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='账号 ID')
    uuid: str = Field(description='账号 UUID')
    tenant_id: int = Field(description='租户 ID')
    project_id: int = Field(description='项目 ID')
    import_batch_id: int | None = Field(None, description='导入批次 ID')
    telegram_user_id: int | None = Field(None, description='Telegram 用户 ID')
    username: str | None = Field(None, description='Telegram 用户名')
    desired_status: str = Field(description='期望状态')
    observed_status: str = Field(description='观测状态')
    last_seen_at: datetime | None = Field(None, description='最近在线探测时间')
    last_error: str | None = Field(None, description='最近错误摘要')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

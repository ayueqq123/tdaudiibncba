from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class CloneRuleSchemaBase(SchemaBase):
    """Clone 规则基础模型"""

    account_id: int = Field(description='发送账号 ID')
    name: str = Field(description='规则名称')
    mode: Literal['copy', 'forward'] = Field('copy', description='投递模式')
    sync_edit: bool = Field(True, description='是否同步源消息编辑')
    sync_delete: bool = Field(True, description='是否同步源消息删除')
    enabled: bool = Field(True, description='是否启用')
    remark: str | None = Field(None, description='备注')


class CreateCloneRuleParam(CloneRuleSchemaBase):
    """创建 Clone 规则参数"""

    tenant_id: int = Field(description='租户 ID')
    project_id: int = Field(description='项目 ID')


class UpdateCloneRuleParam(SchemaBase):
    """更新 Clone 规则参数(草稿字段,不改已发布快照)"""

    name: str = Field(description='规则名称')
    mode: Literal['copy', 'forward'] = Field(description='投递模式')
    sync_edit: bool = Field(description='是否同步源消息编辑')
    sync_delete: bool = Field(description='是否同步源消息删除')
    enabled: bool = Field(description='是否启用')
    remark: str | None = Field(None, description='备注')


class CloneTargetParam(SchemaBase):
    """Clone 目标参数

    chat 字段支持三种写法:数字群 ID、公开链接/用户名(t.me/xx 或 @xx)、
    邀请链接(t.me/+HASH、joinchat/HASH、tg://join?invite=HASH)。
    链接形式会在服务端解析/自动进群后落为数字 ID。
    """

    source_chat_id: int | str = Field(description='源 chat ID 或链接')
    source_topic_id: int | None = Field(None, description='源 topic')
    target_chat_id: int | str = Field(description='目标 chat ID 或链接')
    target_topic_id: int | None = Field(None, description='目标 topic')
    filters: dict[str, Any] | None = Field(
        None, description="过滤条件,如 {'sender_user_ids': [123]} 只克隆指定发言人的消息"
    )
    remark: str | None = Field(None, description='备注')


class CreateCloneTargetParam(SchemaBase):
    """创建目标参数(service 内部):chat_id 必须是已解析的数字 ID"""

    rule_id: int
    tenant_id: int
    project_id: int
    source_chat_id: int = Field(description='源 chat ID')
    source_chat_ref: str | None = Field(None, description='源群原始标识(链接等,供重新进群)')
    source_topic_id: int | None = Field(None, description='源 topic')
    target_chat_id: int = Field(description='目标 chat ID')
    target_chat_ref: str | None = Field(None, description='目标群原始标识')
    target_topic_id: int | None = Field(None, description='目标 topic')
    joined_account_id: int | None = Field(None, description='已完成进群的账号ID')
    filters: dict[str, Any] | None = None
    remark: str | None = Field(None, description='备注')


class CreateCloneRuleVersionParam(SchemaBase):
    """创建版本快照参数(service 内部)"""

    rule_id: int
    tenant_id: int
    project_id: int
    version: int
    snapshot: dict[str, Any]
    published_by: int
    published_at: datetime


class PublishCloneRuleParam(SchemaBase):
    """发布 Clone 规则参数(乐观锁:expected_version 须等于当前版本)"""

    expected_version: int = Field(description='期望的当前版本号')


class GetCloneTargetDetail(CloneTargetParam):
    """Clone 目标详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='目标 ID')
    route_id: str = Field(description='稳定路由 ID')
    source_chat_ref: str | None = Field(None, description='源群原始标识')
    target_chat_ref: str | None = Field(None, description='目标群原始标识')
    rule_id: int = Field(description='规则 ID')
    status: str = Field(description='状态')
    created_time: datetime = Field(description='创建时间')


class GetCloneRuleDetail(CloneRuleSchemaBase):
    """Clone 规则详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='规则 ID')
    uuid: str = Field(description='规则 UUID')
    tenant_id: int = Field(description='租户 ID')
    project_id: int = Field(description='项目 ID')
    current_version: int = Field(description='当前版本号')
    status: str = Field(description='规则状态')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
    targets: list[GetCloneTargetDetail] = Field(default_factory=list, description='目标列表')


class GetCloneRuleVersionDetail(SchemaBase):
    """Clone 规则版本详情(不可变快照)"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='版本 ID')
    rule_id: int = Field(description='规则 ID')
    version: int = Field(description='版本号')
    snapshot: dict[str, Any] = Field(description='发布快照')
    published_by: int = Field(description='发布人')
    published_at: datetime = Field(description='发布时间')

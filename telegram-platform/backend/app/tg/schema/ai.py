from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class CreateAiBindingParam(SchemaBase):
    """注册 AI 绑定:engine='langbot' 走 LangBot HTTP Bot;engine='openai' 直连 OpenAI 兼容接口(炒群)"""

    tenant_id: int
    project_id: int
    account_id: int = Field(description='默认发送账号')
    engine: str = Field(default='langbot', description='引擎: langbot|openai')
    bot_uuid: str = Field(default='', description='LangBot bot UUID')
    base_url: str = Field(default='', description='LangBot 内部地址或 OpenAI 兼容 base_url')
    inbound_secret_ref: str = Field(default='', description='入站签名密钥引用,形如 env:NAME')
    outbound_secret_ref: str = Field(default='', description='回调验签密钥引用,形如 env:NAME')
    chat_id: int | None = Field(default=None, description='绑定群 chat_id(openai 自动触发)')
    topic_id: int | None = Field(default=None, description='绑定话题')
    persona: str | None = Field(default=None, description='人设/系统提示词')
    provider_model: str | None = Field(default=None, description='OpenAI 兼容模型名')
    provider_key: str | None = Field(default=None, description='模型 API key(服务端加密落库,不回显)')
    speak_policy: str = Field(default='all', description='发言策略 all|mention|random')
    random_prob: int = Field(default=30, ge=1, le=100, description='随机发言概率 1-100(speak_policy=random 时生效)')
    context_max_messages: int = Field(default=12, ge=0, le=100, description='发给 AI 的上下文条数')
    auto_approve: bool = Field(default=False, description='自动审批:候选直通发送队列')
    reply_delay_s: int = Field(default=0, ge=0, le=300, description='发言延迟秒数,实际等待 = 该值 ±30%')
    remark: str | None = None


class UpdateAiBindingParam(SchemaBase):
    """更新 AI 绑定(provider_key 留空表示不更换)"""

    account_id: int | None = None
    engine: str | None = None
    base_url: str | None = None
    bot_uuid: str | None = None
    inbound_secret_ref: str | None = None
    outbound_secret_ref: str | None = None
    chat_id: int | None = None
    topic_id: int | None = None
    persona: str | None = None
    provider_model: str | None = None
    provider_key: str | None = None
    speak_policy: str | None = None
    random_prob: int | None = Field(default=None, ge=1, le=100)
    context_max_messages: int | None = Field(default=None, ge=0, le=100)
    auto_approve: bool | None = None
    reply_delay_s: int | None = Field(default=None, ge=0, le=300)
    status: str | None = None
    remark: str | None = None


class SetAutoApproveParam(SchemaBase):
    """批量开关项目内 openai 绑定的自动审批"""

    tenant_id: int
    project_id: int
    enabled: bool


class AiGroupEventParam(SchemaBase):
    """worker 上报的群消息事件(openai 引擎自动触发入口)"""

    api_row_id: int = Field(description='账号 API 行 id')
    chat_id: int
    message_id: int
    text: str = Field(description='消息文本')
    sender_id: int | None = None
    sender_name: str = 'User'
    topic_id: int | None = None


class AiTriggerParam(SchemaBase):
    """手动/规则触发一次 AI 生成(§9.2 起点)"""

    binding_id: int
    chat_id: int
    text: str = Field(description='触发消息文本')
    sender_name: str = 'User'
    sender_id: str | None = None
    topic_id: int | None = None
    agent_key: str | None = None
    source_refs: list[dict] | None = Field(default=None, description='触发来源消息集合')
    context_max_messages: int = Field(default=12, ge=0, le=100, description='内嵌上下文条数上限')
    context_override: list[dict] | None = Field(default=None, description='覆盖上下文(群最新消息缓存)')


class CreateAiConversationParam(SchemaBase):
    tenant_id: int
    project_id: int
    account_id: int
    binding_id: int
    chat_id: int
    session_id: str
    topic_id: int | None = None
    agent_key: str | None = None
    context_epoch: int = 0


class CreateAiRunParam(SchemaBase):
    tenant_id: int
    project_id: int
    conversation_id: int
    session_id: str
    trigger_source: dict
    idempotency_key: str
    deadline: datetime
    context_window: dict | None = None


class CreateAiCallbackParam(SchemaBase):
    binding_id: int
    session_id: str
    reply_to: str
    sequence: int
    is_final: bool
    payload: dict
    payload_sha256: str
    received_at: datetime
    ai_run_id: int | None = None
    link_status: str = 'linked'


class GetAiBindingDetail(SchemaBase):
    """绑定详情(secret_ref 可见,密钥值不回显)"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: str
    tenant_id: int
    project_id: int
    account_id: int
    bot_uuid: str
    base_url: str
    inbound_secret_ref: str
    outbound_secret_ref: str
    status: str
    remark: str | None
    engine: str
    chat_id: int | None
    topic_id: int | None
    persona: str | None
    provider_model: str | None
    has_provider_key: bool = False
    speak_policy: str
    reply_delay_s: int
    random_prob: int
    context_max_messages: int
    auto_approve: bool


class GetAiConversationDetail(SchemaBase):
    """会话详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: str
    tenant_id: int
    project_id: int
    account_id: int
    binding_id: int
    chat_id: int
    topic_id: int | None
    agent_key: str | None
    session_id: str
    context_epoch: int
    context_messages: list
    status: str


class GetAiRunDetail(SchemaBase):
    """run 详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: str
    tenant_id: int
    project_id: int
    conversation_id: int
    session_id: str
    status: str
    accepted_message_id: str | None
    idempotency_key: str
    deadline: datetime | None
    expected_seq: int
    context_window: dict | None
    usage: dict | None
    candidate_id: int | None
    last_error: str | None
    completed_at: datetime | None

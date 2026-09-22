from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class CreateAiBindingParam(SchemaBase):
    """注册 LangBot HTTP Bot 绑定"""

    tenant_id: int
    project_id: int
    account_id: int = Field(description='默认发送账号')
    bot_uuid: str = Field(description='LangBot bot UUID')
    base_url: str = Field(description='LangBot 内部地址,如 http://langbot:5300')
    inbound_secret_ref: str = Field(description='入站签名密钥引用,形如 env:NAME')
    outbound_secret_ref: str = Field(description='回调验签密钥引用,形如 env:NAME')
    remark: str | None = None


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

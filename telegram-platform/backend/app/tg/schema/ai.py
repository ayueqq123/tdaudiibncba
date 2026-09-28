from datetime import datetime

from pydantic import ConfigDict, Field, model_validator

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
    chat_id: int | str | None = Field(
        default=None, description='绑定群:chat_id 或 t.me 链接/用户名(openai 自动触发)'
    )
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
    chat_id: int | str | None = None
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
    reply_to_message_id: int | None = None
    chat_class: str | None = Field(default=None, description='group|channel|private')
    sender_is_bot: bool = False


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
    mode: str = Field(default='reply', description='reply|warmup|script')
    script_line: str | None = None
    rewrite: bool = False


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


class _GroupFields(SchemaBase):
    name: str | None = Field(default=None, max_length=64)
    theme: str | None = Field(default=None, description='群主题/背景')
    base_url: str | None = None
    provider_model: str | None = None
    provider_key: str | None = Field(default=None, description='API key(加密落库不回显,留空不更换)')
    reply_min: int | None = Field(default=None, ge=0, le=20)
    reply_max: int | None = Field(default=None, ge=1, le=20)
    account_cooldown_s: int | None = Field(default=None, ge=0, le=86400)
    account_hourly_max: int | None = Field(default=None, ge=0, le=1000)
    stale_max_messages: int | None = Field(default=None, ge=0, le=100)
    context_max_messages: int | None = Field(default=None, ge=0, le=100)
    bot_chain_max: int | None = Field(default=None, ge=0, le=10)
    active_start_hour: int | None = Field(default=None, ge=0, le=23)
    active_end_hour: int | None = Field(default=None, ge=0, le=23)
    mention_bypass_hours: bool | None = None
    idle_warmup_min: int | None = Field(default=None, ge=0, le=1440)
    quote_prob: int | None = Field(default=None, ge=0, le=100)
    blocked_words: list[str] | None = None
    max_reply_chars: int | None = Field(default=None, ge=0, le=2000)
    auto_approve: bool | None = None
    status: str | None = Field(default=None, pattern='^(active|paused)$')
    remark: str | None = None

    @model_validator(mode='after')
    def _check_range(self) -> '_GroupFields':
        if self.reply_min is not None and self.reply_max is not None and self.reply_max < self.reply_min:
            raise ValueError('最多接话号数不能小于最少接话号数')
        return self


class CreateAiGroupParam(_GroupFields):
    """新建炒群任务:chat 可填数字 ID / t.me 链接 / @用户名"""

    tenant_id: int
    project_id: int
    name: str = Field(max_length=64)
    chat: str = Field(description='群 ID 或链接')
    topic_id: int | None = None
    join_account_id: int | None = Field(default=None, description='用于解析链接/进群的账号')


class UpdateAiGroupParam(_GroupFields):
    """更新炒群任务(未传字段不改)"""


class GetAiGroupDetail(SchemaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    project_id: int
    name: str
    chat_id: int
    chat_ref: str | None
    topic_id: int | None
    theme: str | None
    base_url: str
    provider_model: str | None
    has_provider_key: bool = False
    status: str
    reply_min: int
    reply_max: int
    account_cooldown_s: int
    account_hourly_max: int
    stale_max_messages: int
    context_max_messages: int
    bot_chain_max: int
    active_start_hour: int
    active_end_hour: int
    mention_bypass_hours: bool
    idle_warmup_min: int
    quote_prob: int
    blocked_words: list
    max_reply_chars: int
    auto_approve: bool
    last_message_at: datetime | None
    last_warmup_at: datetime | None
    remark: str | None
    member_count: int = 0
    active_member_count: int = 0
    today_replies: int = 0
    pending_approvals: int = 0


class AiMemberParam(SchemaBase):
    """炒群成员(账号 + 独立人设)"""

    account_id: int | None = None
    role_name: str | None = Field(default=None, max_length=64)
    persona: str | None = None
    talkativeness: int | None = Field(default=None, ge=0, le=100, description='活跃度 0=只在被@时说话')
    reply_delay_s: int | None = Field(default=None, ge=0, le=300)
    provider_model: str | None = Field(default=None, description='单独模型(空=用群设置)')
    provider_key: str | None = Field(default=None, description='单独 key(空=用群设置)')
    base_url: str | None = None
    status: str | None = Field(default=None, pattern='^(active|paused)$')


class GetAiMemberDetail(SchemaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int | None
    account_id: int
    role_name: str | None
    persona: str | None
    talkativeness: int
    reply_delay_s: int
    provider_model: str | None
    base_url: str
    has_provider_key: bool = False
    status: str
    account_label: str = ''
    account_running: bool = False


class AiPersonaParam(SchemaBase):
    tenant_id: int
    project_id: int
    name: str = Field(max_length=64)
    role_name: str | None = Field(default=None, max_length=64)
    persona: str = ''
    talkativeness: int = Field(default=30, ge=0, le=100)


class GetAiPersonaDetail(AiPersonaParam):
    model_config = ConfigDict(from_attributes=True)

    id: int


class AiScriptLine(SchemaBase):
    member_id: int
    text: str = Field(min_length=1, max_length=1000)


class AiScriptParam(SchemaBase):
    name: str = Field(max_length=64)
    lines: list[AiScriptLine] = Field(min_length=1, max_length=50)
    interval_s: int = Field(default=30, ge=3, le=3600)
    rewrite: bool = False


class GetAiScriptDetail(SchemaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    name: str
    lines: list
    interval_s: int
    rewrite: bool
    status: str
    cursor: int


class AiPrivateReplyParam(SchemaBase):
    enabled: bool = True
    reply_text: str | None = None
    reply_cooldown_min: int = Field(default=60, ge=0, le=10080)
    forward_chat_id: int | None = None


class GetAiPrivateReplyDetail(AiPrivateReplyParam):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    project_id: int
    account_id: int


class GetAiGroupRunDetail(SchemaBase):
    """发言记录:一次生成的调度结果"""

    id: int
    created_time: datetime
    status: str
    mode: str
    member_id: int | None
    role_name: str | None
    account_label: str
    trigger_text: str
    trigger_sender: str | None
    content: str | None
    candidate_status: str | None
    last_error: str | None
    model: str | None

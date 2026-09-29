from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key
from backend.database.db import uuid4_str


class TgAiBinding(Base):
    """LangBot HTTP Bot 绑定(§9.5):binding 决定租户/项目与密钥引用。

    secret 不落库明文:inbound_secret_ref / outbound_secret_ref 是
    `env:<ENV_NAME>` 形式的引用,运行时从环境解析;接 KMS 时替换解析器。
    """

    __tablename__ = 'tg_ai_binding'

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(init=False, default_factory=uuid4_str, unique=True)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    account_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='默认发送账号ID')
    bot_uuid: Mapped[str] = mapped_column(sa.String(64), index=True, comment='LangBot bot UUID')
    base_url: Mapped[str] = mapped_column(sa.String(255), comment='LangBot 内部地址,如 http://langbot:5300')
    inbound_secret_ref: Mapped[str] = mapped_column(sa.String(128), comment='入站签名密钥引用 env:NAME')
    outbound_secret_ref: Mapped[str] = mapped_column(sa.String(128), comment='回调验签密钥引用 env:NAME')
    status: Mapped[str] = mapped_column(sa.String(20), default='active', index=True)
    remark: Mapped[str | None] = mapped_column(sa.String(255), default=None)
    # ---- 炒群配置(engine='openai' 时生效)----
    engine: Mapped[str] = mapped_column(sa.String(20), default='langbot', index=True, comment='引擎 langbot|openai')
    chat_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='绑定群 chat_id')
    topic_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='绑定话题')
    persona: Mapped[str | None] = mapped_column(sa.Text, default=None, comment='人设/系统提示词')
    provider_model: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='OpenAI 兼容模型名')
    provider_key_enc: Mapped[str | None] = mapped_column(sa.String(1024), default=None, comment='模型 API key 密文(ItsDCipher)')
    speak_policy: Mapped[str] = mapped_column(sa.String(20), default='all', comment='发言策略 all|mention|random')
    reply_delay_s: Mapped[int] = mapped_column(sa.Integer, default=0, comment='发言延迟秒数 0-300,随机 ±30%')
    random_prob: Mapped[int] = mapped_column(sa.Integer, default=30, comment='随机发言概率 1-100(speak_policy=random)')
    context_max_messages: Mapped[int] = mapped_column(sa.Integer, default=12, comment='发给 AI 的上下文条数 0-100')
    auto_approve: Mapped[bool] = mapped_column(sa.Boolean, default=False, comment='自动审批:候选直通发送队列')
    recent_messages: Mapped[list] = mapped_column(
        sa.JSON, default_factory=list, comment='群最新消息缓存(ring buffer,最多 100 条)'
    )
    group_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='所属炒群任务')
    role_name: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='角色名')

    __table_args__ = ({'comment': 'TG AI LangBot 绑定表'},)

    @property
    def has_provider_key(self) -> bool:
        return bool(self.provider_key_enc)


class TgAiConversation(Base):
    """AI 会话(§9.3):session_id 服务端生成,含 context_epoch 供历史重建。"""

    __tablename__ = 'tg_ai_conversation'

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(init=False, default_factory=uuid4_str, unique=True)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    account_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='账号ID')
    binding_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey('tg_ai_binding.id'), index=True, comment='绑定ID'
    )
    chat_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='群 chat ID')
    # session_id 逻辑 = tenant+project+chat+topic+agent+context_epoch(§9.3)
    session_id: Mapped[str] = mapped_column(sa.String(96), unique=True, index=True, comment='LangBot session_id')
    topic_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='topic')
    agent_key: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='Agent 键')
    context_epoch: Mapped[int] = mapped_column(default=0, comment='上下文代次(重建时递增)')
    # 平台真相源:最近 N 条已发送对话(D0:每 turn 内嵌进 inbound message)
    context_messages: Mapped[list] = mapped_column(sa.JSON, default_factory=list, comment='有界已发送上下文')
    status: Mapped[str] = mapped_column(
        sa.String(20), default='open', index=True, comment='open/locked(有未完成 run)'
    )

    __table_args__ = (
        sa.UniqueConstraint(
            'tenant_id', 'project_id', 'chat_id', 'topic_id', 'agent_key', 'context_epoch',
            name='uq_tg_ai_conv_scope_epoch',
        ),
        {'comment': 'TG AI 会话表'},
    )


class TgAiRun(Base):
    """一次 AI 生成(§9.2):pending→dispatched→running→completed|incomplete|failed|cancelled。"""

    __tablename__ = 'tg_ai_run'

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(init=False, default_factory=uuid4_str, unique=True)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    conversation_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey('tg_ai_conversation.id'), index=True, comment='会话ID'
    )
    session_id: Mapped[str] = mapped_column(sa.String(96), index=True, comment='LangBot session_id')
    trigger_source: Mapped[dict] = mapped_column(sa.JSON, comment='触发来源消息集合(合并须记录)')
    status: Mapped[str] = mapped_column(
        sa.String(20), default='pending', index=True,
        comment='pending/dispatched/running/completed/incomplete/failed/cancelled',
    )
    candidate_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, sa.ForeignKey('tg_reply_candidate.id'), default=None, comment='产出候选'
    )
    accepted_message_id: Mapped[str | None] = mapped_column(
        sa.String(64), default=None, comment='LangBot 202 回执 in_xxx'
    )
    idempotency_key: Mapped[str] = mapped_column(sa.String(64), default_factory=uuid4_str, unique=True)
    deadline: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='回调截止时间')
    expected_seq: Mapped[int] = mapped_column(default=1, comment='期望下一个 sequence')
    context_window: Mapped[dict | None] = mapped_column(
        sa.JSON, default=None, comment='{max_messages, injected_count, strategy}'
    )
    usage: Mapped[dict | None] = mapped_column(sa.JSON, default=None, comment='token/费用结算(§9.5)')
    last_error: Mapped[str | None] = mapped_column(sa.String(255), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None)

    __table_args__ = (
        # 每会话至多一个生成中的 run(§9.3):部分唯一索引需 Postgres,alembic 生成
        sa.Index(
            'uq_tg_ai_run_active_session',
            'session_id',
            unique=True,
            postgresql_where=sa.text(
                "status IN ('pending','dispatched','running')"
            ),
        ),
        {'comment': 'TG AI 运行表'},
    )


class TgAiCallback(Base):
    """LangBot 回调原始落库(§9.5):唯一键防重放;先于 accepted 到达也存。"""

    __tablename__ = 'tg_ai_callback'

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(init=False, default_factory=uuid4_str, unique=True)
    binding_id: Mapped[int] = mapped_column(
        sa.BigInteger, sa.ForeignKey('tg_ai_binding.id'), index=True, comment='绑定ID'
    )
    session_id: Mapped[str] = mapped_column(sa.String(96), index=True)
    reply_to: Mapped[str] = mapped_column(sa.String(64), comment='对应 inbound accepted_message_id')
    sequence: Mapped[int] = mapped_column(comment='会话内单调序号')
    is_final: Mapped[bool] = mapped_column(sa.Boolean, comment='turn 结束')
    payload: Mapped[dict] = mapped_column(sa.JSON, comment='原始回调体')
    payload_sha256: Mapped[str] = mapped_column(sa.String(64), comment='body sha256')
    received_at: Mapped[datetime] = mapped_column(TimeZone, comment='接收时间')
    ai_run_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, sa.ForeignKey('tg_ai_run.id'), default=None, index=True,
        comment='关联 run;reply_to 未匹配时为空'
    )
    link_status: Mapped[str] = mapped_column(
        sa.String(20), default='linked', index=True, comment='linked/pending_link/orphan'
    )

    __table_args__ = (
        sa.UniqueConstraint(
            'binding_id', 'session_id', 'reply_to', 'sequence',
            name='uq_tg_ai_callback_seq',
        ),
        {'comment': 'TG AI 回调表'},
    )


class TgAiGroup(Base):
    """炒群任务(按群):群主题 + 模型 + 节奏;成员 = group_id 指向本任务的 TgAiBinding。"""

    __tablename__ = 'tg_ai_group'

    id: Mapped[id_key] = mapped_column(init=False)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    name: Mapped[str] = mapped_column(sa.String(64), comment='任务名')
    chat_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='群 chat_id')
    chat_ref: Mapped[str | None] = mapped_column(sa.String(255), default=None, comment='群链接/用户名(自动进群用)')
    topic_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='话题')
    theme: Mapped[str | None] = mapped_column(sa.Text, default=None, comment='群主题/背景')
    base_url: Mapped[str] = mapped_column(sa.String(255), default='', comment='OpenAI 兼容 base_url')
    provider_model: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='模型名')
    provider_key_enc: Mapped[str | None] = mapped_column(sa.String(1024), default=None, comment='API key 密文')
    status: Mapped[str] = mapped_column(sa.String(20), default='paused', index=True, comment='active/paused')
    reply_min: Mapped[int] = mapped_column(sa.Integer, default=0, comment='每条消息最少接话号数')
    reply_max: Mapped[int] = mapped_column(sa.Integer, default=1, comment='每条消息最多接话号数')
    account_cooldown_s: Mapped[int] = mapped_column(sa.Integer, default=60, comment='同号两次发言最短间隔秒')
    account_hourly_max: Mapped[int] = mapped_column(sa.Integer, default=20, comment='同号每小时上限,0=不限')
    stale_max_messages: Mapped[int] = mapped_column(sa.Integer, default=10, comment='到点时新增≥N条作废,0=不查')
    context_max_messages: Mapped[int] = mapped_column(sa.Integer, default=12, comment='上下文条数')
    bot_chain_max: Mapped[int] = mapped_column(sa.Integer, default=0, comment='自己号之间最多连续接几轮,0=不互聊')
    active_start_hour: Mapped[int] = mapped_column(sa.Integer, default=0, comment='活跃开始小时(UTC+8)')
    active_end_hour: Mapped[int] = mapped_column(sa.Integer, default=0, comment='活跃结束小时,与开始相同=全天')
    mention_bypass_hours: Mapped[bool] = mapped_column(sa.Boolean, default=True, comment='被@时无视活跃时段')
    idle_warmup_min: Mapped[int] = mapped_column(sa.Integer, default=0, comment='冷场X分钟后暖场,0=关')
    quote_prob: Mapped[int] = mapped_column(sa.Integer, default=30, comment='引用回复概率 0-100')
    punct_space_prob: Mapped[int] = mapped_column(sa.Integer, default=70, comment='逗号句号转空格概率 0-100')
    blocked_words: Mapped[list] = mapped_column(sa.JSON, default_factory=list, comment='关键词黑名单')
    max_reply_chars: Mapped[int] = mapped_column(sa.Integer, default=200, comment='回复最长字数,0=不限')
    auto_approve: Mapped[bool] = mapped_column(sa.Boolean, default=False, comment='自动审批')
    recent_messages: Mapped[list] = mapped_column(sa.JSON, default_factory=list, comment='群最新消息缓存')
    last_message_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='最近群消息时间')
    last_warmup_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='最近暖场时间')
    remark: Mapped[str | None] = mapped_column(sa.String(255), default=None)

    __table_args__ = (
        sa.UniqueConstraint('tenant_id', 'project_id', 'chat_id', 'topic_id', name='uq_tg_ai_group_scope'),
        {'comment': 'TG AI 炒群任务表'},
    )

    @property
    def has_provider_key(self) -> bool:
        return bool(self.provider_key_enc)


class TgAiPersona(Base):
    """人设模板库:成员可一键套用(复制内容,改模板不影响已套用的成员)。"""

    __tablename__ = 'tg_ai_persona'

    id: Mapped[id_key] = mapped_column(init=False)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    name: Mapped[str] = mapped_column(sa.String(64), comment='模板名')
    role_name: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='角色名')
    persona: Mapped[str] = mapped_column(sa.Text, default='', comment='人设内容')
    talkativeness: Mapped[int] = mapped_column(sa.Integer, default=30, comment='建议活跃度')

    __table_args__ = ({'comment': 'TG AI 人设模板表'},)


class TgAiScript(Base):
    """剧本:按顺序由指定成员发出台词(可让 AI 用人设口吻改写),执行一轮即止。"""

    __tablename__ = 'tg_ai_script'

    id: Mapped[id_key] = mapped_column(init=False)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    group_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='炒群任务ID')
    name: Mapped[str] = mapped_column(sa.String(64), comment='剧本名')
    lines: Mapped[list] = mapped_column(sa.JSON, default_factory=list, comment='[{member_id,text}]')
    interval_s: Mapped[int] = mapped_column(sa.Integer, default=30, comment='台词间隔秒(±30%)')
    rewrite: Mapped[bool] = mapped_column(sa.Boolean, default=False, comment='AI 按人设改写台词')
    status: Mapped[str] = mapped_column(sa.String(20), default='idle', comment='idle/running')
    run_token: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='当前执行令牌')
    cursor: Mapped[int] = mapped_column(sa.Integer, default=0, comment='下一句台词下标')

    __table_args__ = ({'comment': 'TG AI 剧本表'},)


class TgAiPrivateReply(Base):
    """私信自动回复/转发(按账号):回复走审批直通发送队列,转发到业务号或群。"""

    __tablename__ = 'tg_ai_private_reply'

    id: Mapped[id_key] = mapped_column(init=False)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    account_id: Mapped[int] = mapped_column(sa.BigInteger, unique=True, comment='账号ID')
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, comment='启用')
    reply_text: Mapped[str | None] = mapped_column(sa.Text, default=None, comment='自动回复内容,空=不回复')
    reply_cooldown_min: Mapped[int] = mapped_column(sa.Integer, default=60, comment='同一人多少分钟内只回一次')
    forward_chat_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='转发到的 chat_id')

    __table_args__ = ({'comment': 'TG AI 私信自动回复表'},)

from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import MappedBase, TimeZone


class RuntimeSharedBase(MappedBase):
    """与 runtime 共享的表:不带平台 mixin(deleted/created_time 等),

    列定义与 telegram-runtime/runtime/storage/models.py 保持一致。"""

    __abstract__ = True


class TgDeliveryJob(RuntimeSharedBase):
    """投递任务(§6.2)。

    与 runtime/storage 的 delivery_job 是同一张共享表:
    表结构由平台 alembic 迁移创建,runtime 以相同列定义读写;
    平台侧只查询,以及 retry/cancel 两个受限状态写。
    tenant_id/project_id/account_id 存平台实体 uuid 字符串。
    """

    __tablename__ = 'delivery_job'

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(36), index=True, comment='租户 uuid')
    project_id: Mapped[str] = mapped_column(sa.String(36), index=True, comment='项目 uuid')
    idempotency_key: Mapped[str] = mapped_column(sa.String(300), unique=True, comment='业务动作幂等键')
    kind: Mapped[str] = mapped_column(sa.String(20), comment='任务类型')
    route_id: Mapped[str] = mapped_column(sa.String(64), index=True, comment='目标路由 ID')
    rule_id: Mapped[str] = mapped_column(sa.String(64), comment='规则标识')
    rule_version: Mapped[int] = mapped_column(sa.Integer, comment='规则版本')
    account_id: Mapped[str] = mapped_column(sa.String(36), index=True, comment='账号 uuid')
    source_scope: Mapped[str] = mapped_column(sa.String(200), comment='源作用域')
    source_chat_id: Mapped[int] = mapped_column(sa.BigInteger, comment='源 chat')
    source_message_id: Mapped[int] = mapped_column(sa.BigInteger, comment='源消息 ID')
    revision: Mapped[int] = mapped_column(sa.Integer, comment='源消息版本')
    target_chat_id: Mapped[int] = mapped_column(sa.BigInteger, comment='目标 chat')
    target_topic_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='目标 topic')
    mode: Mapped[str] = mapped_column(sa.String(10), comment='copy/forward')
    payload_ref: Mapped[str | None] = mapped_column(sa.String(500), default=None, comment='载荷引用')
    payload_hash: Mapped[str | None] = mapped_column(sa.String(128), default=None, comment='载荷 hash')
    requires_approval: Mapped[bool] = mapped_column(default=False, comment='是否需要审批')
    reply_to_target_message_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None)
    grouped_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None)
    status: Mapped[str] = mapped_column(sa.String(30), default='pending', index=True, comment='投递状态')
    attempt_count: Mapped[int] = mapped_column(sa.Integer, default=0, comment='已尝试次数')
    next_attempt_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='下次可执行时间')
    flood_wait_until: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='限流截止')
    last_error_class: Mapped[str | None] = mapped_column(sa.String(40), default=None, comment='最近错误分级')
    created_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='创建时间')
    updated_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='更新时间')

    __table_args__ = ({'comment': 'TG 投递任务表(与 runtime 共享)'},)


class TgDeliveryAttempt(RuntimeSharedBase):
    """投递尝试日志(append-only,平台侧只读)"""

    __tablename__ = 'delivery_attempt'

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey('delivery_job.id'), index=True)
    attempt_no: Mapped[int] = mapped_column(sa.Integer)
    worker_generation: Mapped[int] = mapped_column(sa.Integer)
    started_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None)
    result_status: Mapped[str | None] = mapped_column(sa.String(30), default=None)
    error_class: Mapped[str | None] = mapped_column(sa.String(40), default=None)
    request_ref: Mapped[str | None] = mapped_column(sa.String(200), default=None)

    __table_args__ = ({'comment': 'TG 投递尝试表(append-only)'},)


class TgMessageMap(RuntimeSharedBase):
    """源消息→目标消息映射(平台侧只读;删除标记由 runtime 写)"""

    __tablename__ = 'message_map'

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(36), index=True, comment='租户 uuid')
    project_id: Mapped[str] = mapped_column(sa.String(36), index=True, comment='项目 uuid')
    rule_id: Mapped[str] = mapped_column(sa.String(64))
    route_id: Mapped[str] = mapped_column(sa.String(64), index=True, comment='目标路由 ID')
    rule_version_at_create: Mapped[int] = mapped_column(sa.Integer)
    source_scope: Mapped[str] = mapped_column(sa.String(200))
    source_chat_id: Mapped[int] = mapped_column(sa.BigInteger)
    source_message_id: Mapped[int] = mapped_column(sa.BigInteger, index=True)
    source_album_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None)
    source_member_index: Mapped[int | None] = mapped_column(sa.Integer, default=None)
    sender_account_id: Mapped[str] = mapped_column(sa.String(36), comment='发送账号 uuid')
    target_chat_id: Mapped[int] = mapped_column(sa.BigInteger, index=True)
    target_topic_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None)
    target_message_id: Mapped[int] = mapped_column(sa.BigInteger, index=True)
    output_part_index: Mapped[int] = mapped_column(sa.Integer, default=0)
    last_applied_revision: Mapped[int] = mapped_column(sa.Integer, default=1)
    delivery_job_id: Mapped[str | None] = mapped_column(sa.String(36), default=None)
    status: Mapped[str] = mapped_column(sa.String(30), default='delivered')
    deleted_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None)
    created_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None)
    updated_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None)

    __table_args__ = ({'comment': 'TG 消息映射表'},)

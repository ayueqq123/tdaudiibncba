from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key
from backend.database.db import uuid4_str


class TgReplyCandidate(Base):
    """待审回复候选(§10.1:候选不可变,审批绑定 hash+有效期)"""

    __tablename__ = 'tg_reply_candidate'

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(sa.String(64), init=False, default_factory=uuid4_str, unique=True)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    account_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='账号ID')
    target_chat_id: Mapped[int] = mapped_column(sa.BigInteger, comment='目标 chat')
    content: Mapped[str] = mapped_column(sa.Text, comment='规范化文本内容')
    content_hash: Mapped[str] = mapped_column(sa.String(128), index=True, comment='内容 hash')
    expires_at: Mapped[datetime] = mapped_column(TimeZone, comment='候选过期时间')
    agent_run_id: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='AI 运行标识')
    rule_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='关联规则ID')
    target_topic_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='目标 topic')
    reply_to_source_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='回复目标')
    attachments: Mapped[dict | None] = mapped_column(sa.JSON, default=None, comment='附件版本与校验值')
    version: Mapped[int] = mapped_column(default=1, comment='候选版本(内容变化=新候选)')
    status: Mapped[str] = mapped_column(
        sa.String(20),
        default='pending',
        index=True,
        comment='状态(pending/approved/rejected/expired/consumed/superseded)',
    )

    __table_args__ = ({'comment': 'TG 回复候选表'},)


class TgApproval(Base):
    """审批记录(绑定候选版本+内容 hash+有效期,§10.1)"""

    __tablename__ = 'tg_approval'

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(sa.String(64), init=False, default_factory=uuid4_str, unique=True)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    candidate_id: Mapped[int] = mapped_column(sa.BigInteger, sa.ForeignKey('tg_reply_candidate.id'), index=True)
    candidate_version: Mapped[int] = mapped_column(sa.Integer, comment='绑定的候选版本')
    content_hash: Mapped[str] = mapped_column(sa.String(128), comment='绑定的内容 hash')
    expires_at: Mapped[datetime] = mapped_column(TimeZone, comment='审批有效期(与候选一致)')
    status: Mapped[str] = mapped_column(
        sa.String(20), default='pending', index=True, comment='状态(pending/approved/rejected/expired)'
    )
    reviewer_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='审核人ID')
    decided_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='决定时间')
    reason: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='拒绝/备注原因')

    __table_args__ = ({'comment': 'TG 审批表'},)

from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key
from backend.database.db import uuid4_str


class TgTelegramAccount(Base):
    """TG 平台 Telegram 账号表(§6.2)"""

    __tablename__ = 'tg_telegram_account'
    __table_args__ = (
        sa.UniqueConstraint('telegram_user_id', 'deleted', name='uk_tg_account_tguser_deleted'),
        {'comment': 'TG 平台 Telegram 账号表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(sa.String(64), init=False, default_factory=uuid4_str, unique=True)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    import_batch_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='导入批次ID')
    phone: Mapped[str | None] = mapped_column(sa.String(32), default=None, comment='手机号')
    telegram_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='Telegram 用户ID')
    username: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='Telegram 用户名')
    secret_ref: Mapped[str | None] = mapped_column(
        sa.String(256), default=None, comment='加密会话引用(会话密文不落此表)'
    )
    desired_status: Mapped[str] = mapped_column(sa.String(32), default='stopped', comment='期望状态(stopped/running)')
    observed_status: Mapped[str] = mapped_column(
        sa.String(32),
        default='imported_quarantine',
        index=True,
        comment='观测状态(imported_quarantine/verified/active/reauth_required/revoked/disabled)',
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='最近一次在线探测时间')
    last_error: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='最近错误摘要')
    remark: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='备注')

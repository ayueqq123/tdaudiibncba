from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key
from backend.database.db import uuid4_str


class TgRuntimeCommand(Base):
    """平台 → Worker 命令表(§6.2/§12:命令重放幂等,验证码不入表)"""

    __tablename__ = 'tg_runtime_command'

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(sa.String(64), init=False, default_factory=uuid4_str, unique=True)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    account_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='账号ID')
    type: Mapped[str] = mapped_column(
        sa.String(32),
        index=True,
        comment='命令类型(StartAccount/StopAccount/ReloadConfig/SyncChats/ReconcileSource/CancelJob)',
    )
    issued_by: Mapped[int] = mapped_column(sa.BigInteger, comment='下发人系统用户ID')
    dedup_key: Mapped[str] = mapped_column(
        sa.String(64), default_factory=uuid4_str, unique=True, comment='命令去重键(重放幂等)'
    )
    payload: Mapped[dict | None] = mapped_column(sa.JSON, default=None, comment='命令参数')
    expected_generation: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='期望的账号租约代次')
    deadline: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='过期时间')
    trace_id: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='链路 ID')
    status: Mapped[str] = mapped_column(
        sa.String(16), default='pending', index=True, comment='状态(pending/acknowledged/done/rejected/duplicate)'
    )
    result: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='执行结果摘要')
    acked_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='确认时间')
    finished_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='完成时间')

    __table_args__ = ({'comment': 'TG 平台运行时命令表'},)

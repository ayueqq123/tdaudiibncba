from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key


class TgAlertAck(Base):
    """异常告警处理记录(按告警 key 记住处理时的最近发生时间,之后再发生重新变为未处理)"""

    __tablename__ = 'tg_alert_ack'

    id: Mapped[id_key] = mapped_column(init=False)
    alert_key: Mapped[str] = mapped_column(sa.String(255), unique=True, comment='告警 key')
    handled_last_at: Mapped[datetime | None] = mapped_column(TimeZone, comment='处理时告警的最近发生时间')
    handled_at: Mapped[datetime] = mapped_column(TimeZone, comment='处理时间')
    handled_by: Mapped[str] = mapped_column(sa.String(64), comment='处理人')

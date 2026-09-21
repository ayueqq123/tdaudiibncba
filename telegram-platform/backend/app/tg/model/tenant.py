import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.database.db import uuid4_str


class Tenant(Base):
    """TG 平台租户表"""

    __tablename__ = 'tg_tenant'
    __table_args__ = (
        sa.UniqueConstraint('name', 'deleted', name='uk_tg_tenant_name_deleted'),
        {'comment': 'TG 平台租户表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(sa.String(64), init=False, default_factory=uuid4_str, unique=True)
    name: Mapped[str] = mapped_column(sa.String(128), index=True, comment='租户名称')
    status: Mapped[int] = mapped_column(default=1, index=True, comment='租户状态(0停用 1正常)')
    remark: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='备注')

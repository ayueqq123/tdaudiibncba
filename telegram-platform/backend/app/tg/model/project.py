import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.database.db import uuid4_str


class Project(Base):
    """TG 平台项目表(§6.1:每条项目记录携带 tenant_id)"""

    __tablename__ = 'tg_project'
    __table_args__ = (
        sa.UniqueConstraint('tenant_id', 'name', 'deleted', name='uk_tg_project_tenant_name_deleted'),
        {'comment': 'TG 平台项目表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(sa.String(64), init=False, default_factory=uuid4_str, unique=True)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    name: Mapped[str] = mapped_column(sa.String(128), comment='项目名称')
    status: Mapped[int] = mapped_column(default=1, index=True, comment='项目状态(0停用 1正常)')
    remark: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='备注')

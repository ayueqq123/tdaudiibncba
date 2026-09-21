import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.database.db import uuid4_str


class Membership(Base):
    """TG 平台成员表(§6.2 membership:租户/项目内的用户角色与资源范围)"""

    __tablename__ = 'tg_membership'
    __table_args__ = (
        sa.UniqueConstraint('tenant_id', 'project_id', 'user_id', 'deleted', name='uk_tg_membership_scope_deleted'),
        {'comment': 'TG 平台成员表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(sa.String(64), init=False, default_factory=uuid4_str, unique=True)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='系统用户ID')
    role: Mapped[str] = mapped_column(sa.String(32), default='member', comment='角色(owner/admin/member)')
    status: Mapped[int] = mapped_column(default=1, comment='成员状态(0停用 1正常)')

from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key
from backend.database.db import uuid4_str


class TgCloneRule(Base):
    """Clone 规则草稿(§6.2:规则修改发布新版本,停用优先于快照)"""

    __tablename__ = 'tg_clone_rule'
    __table_args__ = (
        sa.UniqueConstraint('project_id', 'name', 'deleted', name='uk_tg_rule_name_deleted'),
        {'comment': 'TG 平台 Clone 规则表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(sa.String(64), init=False, default_factory=uuid4_str, unique=True)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    account_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='发送账号ID')
    name: Mapped[str] = mapped_column(sa.String(128), comment='规则名称')
    mode: Mapped[str] = mapped_column(sa.String(16), default='copy', comment='模式(copy/forward)')
    sync_edit: Mapped[bool] = mapped_column(default=True, comment='是否同步编辑')
    sync_delete: Mapped[bool] = mapped_column(default=True, comment='是否同步删除')
    enabled: Mapped[bool] = mapped_column(default=True, comment='是否启用')
    current_version: Mapped[int] = mapped_column(default=0, comment='当前已发布版本号(0=未发布)')
    status: Mapped[str] = mapped_column(
        sa.String(16), default='draft', index=True, comment='规则状态(draft/published/disabled)'
    )
    remark: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='备注')


class TgCloneRuleVersion(Base):
    """Clone 规则不可变发布快照(§6.2:版本不可变)"""

    __tablename__ = 'tg_clone_rule_version'
    __table_args__ = (
        sa.UniqueConstraint('rule_id', 'version', name='uk_tg_rule_version'),
        {'comment': 'TG 平台 Clone 规则版本表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(sa.String(64), init=False, default_factory=uuid4_str, unique=True)
    rule_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='规则ID')
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    version: Mapped[int] = mapped_column(comment='版本号(递增)')
    snapshot: Mapped[dict] = mapped_column(sa.JSON, comment='发布快照{rule,targets,filters}')
    published_by: Mapped[int] = mapped_column(sa.BigInteger, comment='发布人系统用户ID')
    published_at: Mapped[datetime] = mapped_column(TimeZone, comment='发布时间')


class TgCloneTarget(Base):
    """Clone 目标路由(§6.2:路由 ID 稳定,删除只退役不复用)"""

    __tablename__ = 'tg_clone_target'

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(sa.String(64), init=False, default_factory=uuid4_str, unique=True)
    rule_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='规则ID')
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    route_id: Mapped[str] = mapped_column(
        sa.String(64), init=False, default_factory=uuid4_str, unique=True, comment='稳定路由ID(跨版本不变)'
    )
    source_chat_id: Mapped[int] = mapped_column(sa.BigInteger, comment='源 chat ID')
    target_chat_id: Mapped[int] = mapped_column(sa.BigInteger, comment='目标 chat ID')
    source_chat_ref: Mapped[str | None] = mapped_column(sa.Text, default=None, comment='源群原始标识(链接,供重新进群)')
    target_chat_ref: Mapped[str | None] = mapped_column(sa.Text, default=None, comment='目标群原始标识')
    source_topic_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='源 topic')
    target_topic_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='目标 topic')
    filters: Mapped[dict | None] = mapped_column(sa.JSON, default=None, comment='过滤条件{keywords,media,...}')
    status: Mapped[str] = mapped_column(sa.String(16), default='active', index=True, comment='状态(active/retired)')
    remark: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='备注')

    __table_args__ = (
        sa.UniqueConstraint('rule_id', 'source_chat_id', 'source_topic_id', 'deleted', name='uk_tg_target_src_deleted'),
        {'comment': 'TG 平台 Clone 目标表'},
    )

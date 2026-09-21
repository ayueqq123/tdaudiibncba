from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key
from backend.database.db import uuid4_str


class TgImportBatch(Base):
    """TG 平台 Session 导入批次表(§5.1.1 审计)"""

    __tablename__ = 'tg_import_batch'
    __table_args__ = ({'comment': 'TG 平台 Session 导入批次表'},)

    id: Mapped[id_key] = mapped_column(init=False)
    uuid: Mapped[str] = mapped_column(sa.String(64), init=False, default_factory=uuid4_str, unique=True)
    tenant_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='租户ID')
    project_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='项目ID')
    operator_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='操作者系统用户ID')
    filename: Mapped[str] = mapped_column(sa.String(256), comment='上传文件名')
    file_sha256: Mapped[str] = mapped_column(sa.String(64), comment='上传文件 SHA-256')
    total: Mapped[int] = mapped_column(default=0, comment='包内 session 总数')
    verified: Mapped[int] = mapped_column(default=0, comment='验证通过数')
    failed: Mapped[int] = mapped_column(default=0, comment='验证失败数')
    status: Mapped[str] = mapped_column(
        sa.String(32), default='processing', index=True, comment='批次状态(processing/completed/failed)'
    )
    detail: Mapped[list | None] = mapped_column(
        sa.JSON, default=None, comment='逐项结果[{key,status,user_id,username,two_fa,spamblock,detail}]'
    )
    finished_at: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='批次完成时间')

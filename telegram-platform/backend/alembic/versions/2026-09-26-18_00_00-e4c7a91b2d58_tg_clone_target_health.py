"""tg_clone_target: 路线健康列

Revision ID: e4c7a91b2d58
Revises: d9b3e72f4a16
Create Date: 2026-09-26 18:00:00.000000

joined_at 记录最近一次进群时间;health_reason 记录检测到的失效原因(账号不在群内等)。
"""

import sqlalchemy as sa

from alembic import op

revision = 'e4c7a91b2d58'
down_revision = 'd9b3e72f4a16'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tg_clone_target', sa.Column('joined_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('tg_clone_target', sa.Column('health_reason', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('tg_clone_target', 'health_reason')
    op.drop_column('tg_clone_target', 'joined_at')

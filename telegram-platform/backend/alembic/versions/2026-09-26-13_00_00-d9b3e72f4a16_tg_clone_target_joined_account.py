"""tg_clone_target: 已进群账号列

Revision ID: d9b3e72f4a16
Revises: c8a2f61e3d05
Create Date: 2026-09-26 13:00:00.000000

记录目标已由哪个账号完成进群,规则运行时同账号不再重复起 Telegram 连接进群。
"""

import sqlalchemy as sa

from alembic import op

revision = 'd9b3e72f4a16'
down_revision = 'c8a2f61e3d05'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tg_clone_target', sa.Column('joined_account_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('tg_clone_target', 'joined_account_id')

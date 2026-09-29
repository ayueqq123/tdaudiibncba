"""tg_ai_group: 标点转空格概率列

Revision ID: f2a8c41d9e03
Revises: e4c7a91b2d58
Create Date: 2026-09-28 08:00:00.000000

punct_space_prob 控制回复发送前把逗号句号类标点替换为空格的概率(0-100)。
"""

import sqlalchemy as sa

from alembic import op

revision = 'f2a8c41d9e03'
down_revision = 'e4c7a91b2d58'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tg_ai_group',
        sa.Column('punct_space_prob', sa.Integer(), nullable=False, server_default='70'),
    )


def downgrade() -> None:
    op.drop_column('tg_ai_group', 'punct_space_prob')

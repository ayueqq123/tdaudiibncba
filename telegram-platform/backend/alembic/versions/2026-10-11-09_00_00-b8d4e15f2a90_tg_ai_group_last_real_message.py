"""tg_ai_group: 最近真实消息时间列

Revision ID: b8d4e15f2a90
Revises: a3f7b29e41d5
Create Date: 2026-10-11 09:00:00.000000

last_real_message_at 只在非克隆消息时刷新,冷场暖场按它判空场——
克隆搬运刷屏不再让群被误判为活跃,搬运群里的暖场才能正常触发。
"""

import sqlalchemy as sa

from alembic import op

revision = 'b8d4e15f2a90'
down_revision = 'a3f7b29e41d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tg_ai_group',
        sa.Column('last_real_message_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('tg_ai_group', 'last_real_message_at')

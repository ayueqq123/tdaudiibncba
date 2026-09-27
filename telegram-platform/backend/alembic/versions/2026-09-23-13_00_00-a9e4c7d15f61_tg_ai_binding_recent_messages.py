"""tg_ai_binding add recent_messages

Revision ID: a9e4c7d15f61
Revises: f8d3b6c94e50
Create Date: 2026-09-23 13:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'a9e4c7d15f61'
down_revision = 'f8d3b6c94e50'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tg_ai_binding',
        sa.Column('recent_messages', sa.JSON(), nullable=True, comment='群最新消息缓存(ring buffer,最多 100 条)'),
    )


def downgrade() -> None:
    op.drop_column('tg_ai_binding', 'recent_messages')

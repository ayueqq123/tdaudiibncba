"""tg_ai_binding add context_max_messages

Revision ID: f8d3b6c94e50
Revises: e7c2a5b83d49
Create Date: 2026-09-23 12:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'f8d3b6c94e50'
down_revision = 'e7c2a5b83d49'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tg_ai_binding',
        sa.Column('context_max_messages', sa.Integer(), server_default='12', nullable=False, comment='发给 AI 的上下文条数 0-100'),
    )


def downgrade() -> None:
    op.drop_column('tg_ai_binding', 'context_max_messages')

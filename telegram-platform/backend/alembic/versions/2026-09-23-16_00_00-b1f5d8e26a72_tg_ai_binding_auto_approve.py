"""tg_ai_binding add auto_approve

Revision ID: b1f5d8e26a72
Revises: a9e4c7d15f61
Create Date: 2026-09-23 16:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'b1f5d8e26a72'
down_revision = 'a9e4c7d15f61'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tg_ai_binding',
        sa.Column('auto_approve', sa.Boolean(), server_default='false', nullable=False, comment='自动审批:候选直通发送队列'),
    )


def downgrade() -> None:
    op.drop_column('tg_ai_binding', 'auto_approve')

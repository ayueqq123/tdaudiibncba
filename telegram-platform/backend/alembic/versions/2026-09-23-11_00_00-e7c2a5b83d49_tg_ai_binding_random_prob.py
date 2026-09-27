"""tg_ai_binding add random_prob

Revision ID: e7c2a5b83d49
Revises: d6b1f4a92c38
Create Date: 2026-09-23 11:00:00.000000
"""
import sqlalchemy as sa

from alembic import op

revision = 'e7c2a5b83d49'
down_revision = 'd6b1f4a92c38'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tg_ai_binding',
        sa.Column('random_prob', sa.Integer(), server_default='30', nullable=False, comment='随机发言概率 1-100(speak_policy=random)'),
    )


def downgrade() -> None:
    op.drop_column('tg_ai_binding', 'random_prob')

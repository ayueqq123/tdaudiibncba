"""clone delay, account usage, and target sender status

Revision ID: c1a2e3d4f5a6
Revises: 5d17e30d7620
Create Date: 2026-10-14 13:45:09
"""

import sqlalchemy as sa

from alembic import op

revision = 'c1a2e3d4f5a6'
down_revision = '5d17e30d7620'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tg_clone_rule',
        sa.Column('delay_min_s', sa.Integer(), server_default='0', nullable=False),
    )
    op.add_column(
        'tg_clone_rule',
        sa.Column('delay_max_s', sa.Integer(), server_default='0', nullable=False),
    )
    op.add_column('tg_telegram_account', sa.Column('usage', sa.String(length=16), nullable=True))
    op.create_index('ix_tg_telegram_account_usage', 'tg_telegram_account', ['usage'])
    op.add_column(
        'tg_clone_target',
        sa.Column('sender_status', sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('tg_clone_target', 'sender_status')
    op.drop_index('ix_tg_telegram_account_usage', table_name='tg_telegram_account')
    op.drop_column('tg_telegram_account', 'usage')
    op.drop_column('tg_clone_rule', 'delay_max_s')
    op.drop_column('tg_clone_rule', 'delay_min_s')

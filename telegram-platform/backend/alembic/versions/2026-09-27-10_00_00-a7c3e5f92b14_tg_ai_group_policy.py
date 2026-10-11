"""tg_ai_group_policy

Revision ID: a7c3e5f92b14
Revises: f1d8a3c6b742
Create Date: 2026-09-27 10:00:00

"""

import sqlalchemy as sa

from alembic import op

revision = 'a7c3e5f92b14'
down_revision = 'f1d8a3c6b742'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'tg_ai_group_policy',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.BigInteger(), nullable=False),
        sa.Column('project_id', sa.BigInteger(), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('topic_id', sa.BigInteger(), nullable=True),
        sa.Column('reply_min', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('reply_max', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('account_cooldown_s', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('account_hourly_max', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('stale_max_messages', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('deleted', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('deleted_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_time', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'project_id', 'chat_id', 'topic_id', name='uq_tg_ai_group_policy_scope'),
        comment='TG AI 炒群群策略表',
    )
    op.create_index('ix_tg_ai_group_policy_tenant_id', 'tg_ai_group_policy', ['tenant_id'])
    op.create_index('ix_tg_ai_group_policy_project_id', 'tg_ai_group_policy', ['project_id'])


def downgrade() -> None:
    op.drop_table('tg_ai_group_policy')

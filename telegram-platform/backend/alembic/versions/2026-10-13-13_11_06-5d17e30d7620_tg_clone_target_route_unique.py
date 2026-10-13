"""允许同一源群路由到多个目标群

Revision ID: 5d17e30d7620
Revises: c5e7d91a3b46
Create Date: 2026-10-13 13:11:06
"""

from alembic import op

revision = '5d17e30d7620'
down_revision = 'c5e7d91a3b46'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('uk_tg_target_src_deleted', 'tg_clone_target', type_='unique')
    op.create_unique_constraint(
        'uk_tg_target_route_deleted',
        'tg_clone_target',
        ['rule_id', 'source_chat_id', 'source_topic_id', 'target_chat_id', 'target_topic_id', 'deleted'],
    )


def downgrade() -> None:
    op.drop_constraint('uk_tg_target_route_deleted', 'tg_clone_target', type_='unique')
    op.create_unique_constraint(
        'uk_tg_target_src_deleted',
        'tg_clone_target',
        ['rule_id', 'source_chat_id', 'source_topic_id', 'deleted'],
    )

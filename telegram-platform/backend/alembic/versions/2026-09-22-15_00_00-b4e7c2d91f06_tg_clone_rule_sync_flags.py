"""tg_clone_rule_sync_flags

Revision ID: b4e7c2d91f06
Revises: 9f3a21c7b5d4
Create Date: 2026-09-22 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4e7c2d91f06'
down_revision = '9f3a21c7b5d4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'tg_clone_rule',
        sa.Column('sync_edit', sa.Boolean(), server_default='true', nullable=False, comment='是否同步编辑'),
    )
    op.add_column(
        'tg_clone_rule',
        sa.Column('sync_delete', sa.Boolean(), server_default='true', nullable=False, comment='是否同步删除'),
    )


def downgrade():
    op.drop_column('tg_clone_rule', 'sync_delete')
    op.drop_column('tg_clone_rule', 'sync_edit')

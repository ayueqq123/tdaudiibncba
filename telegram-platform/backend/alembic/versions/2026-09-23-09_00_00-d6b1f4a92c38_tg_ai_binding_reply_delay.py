"""tg_ai_binding_reply_delay

Revision ID: d6b1f4a92c38
Revises: c5a9e3f81b27
Create Date: 2026-09-23 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd6b1f4a92c38'
down_revision = 'c5a9e3f81b27'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'tg_ai_binding',
        sa.Column('reply_delay_s', sa.Integer(), server_default='0', nullable=False, comment='发言延迟秒数 0-300'),
    )


def downgrade():
    op.drop_column('tg_ai_binding', 'reply_delay_s')

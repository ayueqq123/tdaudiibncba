"""sys_user_last_password

Revision ID: 9f3a21c7b5d4
Revises: fd6cc8a2cfc9
Create Date: 2026-09-22 13:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f3a21c7b5d4'
down_revision = 'fd6cc8a2cfc9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'sys_user',
        sa.Column('last_password', sa.String(length=256), nullable=True,
                  comment='最近一次设置的密码明文(仅超管可见)'),
    )


def downgrade():
    op.drop_column('sys_user', 'last_password')

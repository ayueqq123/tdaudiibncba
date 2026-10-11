"""tg_alert_ack

Revision ID: f1d8a3c6b742
Revises: e4c7a91b2d58
Create Date: 2026-09-26 20:00:00

"""

import sqlalchemy as sa

from alembic import op

revision = 'f1d8a3c6b742'
down_revision = 'e4c7a91b2d58'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'tg_alert_ack',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('alert_key', sa.String(length=255), nullable=False),
        sa.Column('handled_last_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('handled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('handled_by', sa.String(length=64), nullable=False),
        sa.Column('deleted', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('deleted_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_time', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('alert_key'),
    )


def downgrade() -> None:
    op.drop_table('tg_alert_ack')

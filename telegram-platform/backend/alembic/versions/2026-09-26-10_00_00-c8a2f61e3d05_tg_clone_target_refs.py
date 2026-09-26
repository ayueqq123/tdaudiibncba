"""tg_clone_target: 源/目标群原始标识(链接)列

Revision ID: c8a2f61e3d05
Revises: b1f5d8e26a72
Create Date: 2026-09-26 10:00:00.000000

支持规则目标填 t.me 链接/邀请链接:服务端解析进群后落数字 ID,
原始标识留存供发布时重新进群验证。
"""

import sqlalchemy as sa

from alembic import op

revision = 'c8a2f61e3d05'
down_revision = 'b1f5d8e26a72'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tg_clone_target', sa.Column('source_chat_ref', sa.Text(), nullable=True))
    op.add_column('tg_clone_target', sa.Column('target_chat_ref', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('tg_clone_target', 'target_chat_ref')
    op.drop_column('tg_clone_target', 'source_chat_ref')

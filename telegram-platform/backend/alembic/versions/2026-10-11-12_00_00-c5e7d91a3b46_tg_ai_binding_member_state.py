"""tg_ai_binding 增加在群状态字段

Revision ID: c5e7d91a3b46
Revises: b8d4e15f2a90
Create Date: 2026-10-11 12:00:00

成员在群巡检(tg_ai_member_check)把 GetParticipant 结果写回:
member_state ok|not_in_group|muted|banned|session_dead|frozen|check_failed,
member_state_detail 原因,member_state_at 检查时间。
"""

from alembic import op

import sqlalchemy as sa


revision = 'c5e7d91a3b46'
down_revision = 'b8d4e15f2a90'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tg_ai_binding', sa.Column('member_state', sa.String(length=24), nullable=True))
    op.add_column('tg_ai_binding', sa.Column('member_state_detail', sa.String(length=500), nullable=True))
    op.add_column('tg_ai_binding', sa.Column('member_state_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('tg_ai_binding', 'member_state_at')
    op.drop_column('tg_ai_binding', 'member_state_detail')
    op.drop_column('tg_ai_binding', 'member_state')

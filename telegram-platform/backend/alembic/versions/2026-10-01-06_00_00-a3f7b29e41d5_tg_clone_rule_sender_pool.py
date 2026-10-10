"""tg_clone_rule: 发送号池 + 克隆改写/广告拦截配置;tg_clone_target: 池内进群记录

Revision ID: a3f7b29e41d5
Revises: f2a8c41d9e03
Create Date: 2026-10-01 06:00:00.000000

sender_account_ids 为多号搬运的发送号池(空=仅监听号发送,兼容存量);
ai_rewrite/ad_block/ad_keywords/ai_group_id 为克隆内容变形闸配置
(由控制面 clone_transform 接口读取,不进发布快照);
joined_account_ids 记录池内每个号进目标群的状态。
"""

import sqlalchemy as sa

from alembic import op

revision = 'a3f7b29e41d5'
down_revision = 'f2a8c41d9e03'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'tg_clone_rule',
        sa.Column('sender_account_ids', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json"), comment='发送号池(行ID列表)'),
    )
    op.add_column(
        'tg_clone_rule',
        sa.Column('ai_rewrite', sa.String(16), nullable=False, server_default='off', comment='克隆文本改写'),
    )
    op.add_column(
        'tg_clone_rule',
        sa.Column('ad_block', sa.String(16), nullable=False, server_default='off', comment='广告拦截方式'),
    )
    op.add_column(
        'tg_clone_rule',
        sa.Column('ad_keywords', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json"), comment='广告关键词列表'),
    )
    op.add_column(
        'tg_clone_rule',
        sa.Column('ai_group_id', sa.BigInteger(), nullable=True, comment='复用的 AI 群配置'),
    )
    op.add_column(
        'tg_clone_target',
        sa.Column('joined_account_ids', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json"), comment='已进目标群的池内账号'),
    )


def downgrade() -> None:
    op.drop_column('tg_clone_target', 'joined_account_ids')
    op.drop_column('tg_clone_rule', 'ai_group_id')
    op.drop_column('tg_clone_rule', 'ad_keywords')
    op.drop_column('tg_clone_rule', 'ad_block')
    op.drop_column('tg_clone_rule', 'ai_rewrite')
    op.drop_column('tg_clone_rule', 'sender_account_ids')

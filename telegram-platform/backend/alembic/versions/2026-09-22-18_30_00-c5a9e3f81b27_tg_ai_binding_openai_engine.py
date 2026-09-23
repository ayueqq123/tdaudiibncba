"""tg_ai_binding_openai_engine

Revision ID: c5a9e3f81b27
Revises: b4e7c2d91f06
Create Date: 2026-09-22 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c5a9e3f81b27'
down_revision = 'b4e7c2d91f06'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'tg_ai_binding',
        sa.Column('engine', sa.String(20), server_default='langbot', nullable=False, comment='引擎 langbot|openai'),
    )
    op.add_column(
        'tg_ai_binding',
        sa.Column('chat_id', sa.BigInteger(), nullable=True, comment='绑定群 chat_id'),
    )
    op.add_column(
        'tg_ai_binding',
        sa.Column('topic_id', sa.BigInteger(), nullable=True, comment='绑定话题'),
    )
    op.add_column(
        'tg_ai_binding',
        sa.Column('persona', sa.Text(), nullable=True, comment='人设/系统提示词'),
    )
    op.add_column(
        'tg_ai_binding',
        sa.Column('provider_model', sa.String(64), nullable=True, comment='OpenAI 兼容模型名'),
    )
    op.add_column(
        'tg_ai_binding',
        sa.Column('provider_key_enc', sa.String(1024), nullable=True, comment='模型 API key 密文(ItsDCipher)'),
    )
    op.add_column(
        'tg_ai_binding',
        sa.Column('speak_policy', sa.String(20), server_default='all', nullable=False, comment='发言策略 all|mention'),
    )


def downgrade():
    op.drop_column('tg_ai_binding', 'speak_policy')
    op.drop_column('tg_ai_binding', 'provider_key_enc')
    op.drop_column('tg_ai_binding', 'provider_model')
    op.drop_column('tg_ai_binding', 'persona')
    op.drop_column('tg_ai_binding', 'topic_id')
    op.drop_column('tg_ai_binding', 'chat_id')
    op.drop_column('tg_ai_binding', 'engine')

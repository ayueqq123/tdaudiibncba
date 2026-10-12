"""tg_ai_group: 炒群按群组织(任务/成员/人设库/剧本/私信),旧绑定按群合并迁移

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


def _base_cols() -> list[sa.Column]:
    return [
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.BigInteger(), nullable=False, index=True),
        sa.Column('project_id', sa.BigInteger(), nullable=False, index=True),
    ]


def _tail_cols() -> list:
    return [
        sa.Column('deleted', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('deleted_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_time', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    ]


def upgrade() -> None:
    op.create_table(
        'tg_ai_group',
        *_base_cols(),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False, index=True),
        sa.Column('chat_ref', sa.String(255), nullable=True),
        sa.Column('topic_id', sa.BigInteger(), nullable=True),
        sa.Column('theme', sa.Text(), nullable=True),
        sa.Column('base_url', sa.String(255), nullable=False, server_default=''),
        sa.Column('provider_model', sa.String(64), nullable=True),
        sa.Column('provider_key_enc', sa.String(1024), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='paused', index=True),
        sa.Column('reply_min', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reply_max', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('account_cooldown_s', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('account_hourly_max', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('stale_max_messages', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('context_max_messages', sa.Integer(), nullable=False, server_default='12'),
        sa.Column('bot_chain_max', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active_start_hour', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('active_end_hour', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('mention_bypass_hours', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('idle_warmup_min', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('quote_prob', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('blocked_words', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('max_reply_chars', sa.Integer(), nullable=False, server_default='200'),
        sa.Column('auto_approve', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('recent_messages', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_warmup_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('remark', sa.String(255), nullable=True),
        *_tail_cols(),
        sa.UniqueConstraint('tenant_id', 'project_id', 'chat_id', 'topic_id', name='uq_tg_ai_group_scope'),
        comment='TG AI 炒群任务表',
    )
    op.create_table(
        'tg_ai_persona',
        *_base_cols(),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('role_name', sa.String(64), nullable=True),
        sa.Column('persona', sa.Text(), nullable=False, server_default=''),
        sa.Column('talkativeness', sa.Integer(), nullable=False, server_default='30'),
        *_tail_cols(),
        comment='TG AI 人设模板表',
    )
    op.create_table(
        'tg_ai_script',
        *_base_cols(),
        sa.Column('group_id', sa.BigInteger(), nullable=False, index=True),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('lines', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('interval_s', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('rewrite', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('status', sa.String(20), nullable=False, server_default='idle'),
        sa.Column('run_token', sa.String(64), nullable=True),
        sa.Column('cursor', sa.Integer(), nullable=False, server_default='0'),
        *_tail_cols(),
        comment='TG AI 剧本表',
    )
    op.create_table(
        'tg_ai_private_reply',
        *_base_cols(),
        sa.Column('account_id', sa.BigInteger(), nullable=False, unique=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('reply_text', sa.Text(), nullable=True),
        sa.Column('reply_cooldown_min', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('forward_chat_id', sa.BigInteger(), nullable=True),
        *_tail_cols(),
        comment='TG AI 私信自动回复表',
    )
    op.add_column('tg_ai_binding', sa.Column('group_id', sa.BigInteger(), nullable=True))
    op.add_column('tg_ai_binding', sa.Column('role_name', sa.String(64), nullable=True))
    op.create_index('ix_tg_ai_binding_group_id', 'tg_ai_binding', ['group_id'])
    migrate_bindings()


def migrate_bindings() -> None:
    """同群(租户+项目+群+话题)的 openai 绑定合并为一个任务,绑定变成员;可重复执行。"""
    op.execute(
        """
        INSERT INTO tg_ai_group (tenant_id, project_id, name, chat_id, topic_id, base_url, provider_model,
            provider_key_enc, status, reply_min, reply_max, context_max_messages, auto_approve, created_time)
        SELECT DISTINCT ON (b.tenant_id, b.project_id, b.chat_id, b.topic_id)
            b.tenant_id, b.project_id, '群 ' || b.chat_id, b.chat_id, b.topic_id, b.base_url, b.provider_model,
            b.provider_key_enc, CASE WHEN b.status = 'active' THEN 'active' ELSE 'paused' END,
            0, 1, b.context_max_messages, b.auto_approve, now()
        FROM tg_ai_binding b
        WHERE b.engine = 'openai' AND b.chat_id IS NOT NULL AND b.deleted = 0 AND b.group_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM tg_ai_group g
              WHERE g.tenant_id = b.tenant_id AND g.project_id = b.project_id AND g.chat_id = b.chat_id
                AND g.topic_id IS NOT DISTINCT FROM b.topic_id AND g.deleted = 0
          )
        ORDER BY b.tenant_id, b.project_id, b.chat_id, b.topic_id, (b.status = 'active') DESC, b.id
        """
    )
    op.execute(
        """
        UPDATE tg_ai_binding b SET group_id = g.id,
            random_prob = CASE b.speak_policy WHEN 'mention' THEN 0 WHEN 'random' THEN b.random_prob ELSE 100 END
        FROM tg_ai_group g
        WHERE b.engine = 'openai' AND b.group_id IS NULL AND b.deleted = 0
          AND g.tenant_id = b.tenant_id AND g.project_id = b.project_id AND g.chat_id = b.chat_id
          AND g.topic_id IS NOT DISTINCT FROM b.topic_id
        """
    )
    # 过渡版「群策略」表(未走迁移、由 create_all 建出)存在则把节奏设置并入任务;旧表保留备查
    if sa.inspect(op.get_bind()).has_table('tg_ai_group_policy'):
        op.execute(
            """
            UPDATE tg_ai_group g SET reply_min = p.reply_min, reply_max = p.reply_max,
                account_cooldown_s = p.account_cooldown_s, account_hourly_max = p.account_hourly_max,
                stale_max_messages = p.stale_max_messages
            FROM tg_ai_group_policy p
            WHERE p.deleted = 0 AND g.tenant_id = p.tenant_id AND g.project_id = p.project_id
              AND g.chat_id = p.chat_id AND g.topic_id IS NOT DISTINCT FROM p.topic_id
            """
        )


def downgrade() -> None:
    op.drop_index('ix_tg_ai_binding_group_id', 'tg_ai_binding')
    op.drop_column('tg_ai_binding', 'role_name')
    op.drop_column('tg_ai_binding', 'group_id')
    for t in ('tg_ai_private_reply', 'tg_ai_script', 'tg_ai_persona', 'tg_ai_group'):
        op.drop_table(t)

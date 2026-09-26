from datetime import timedelta
from typing import Any

import sqlalchemy as sa

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tg.crud.crud_membership import membership_dao
from backend.app.tg.model import (
    TgAiBinding,
    TgAiConversation,
    TgAiRun,
    TgCloneRule,
    TgCloneTarget,
    TgDeliveryJob,
    TgTelegramAccount,
)
from backend.app.tg.service.rule_service import route_health
from backend.utils.timezone import timezone

WINDOW = timedelta(hours=24)
HEARTBEAT_GRACE = timedelta(minutes=3)

ACCOUNT_BAD = {
    'error': ('error', '账号连接失败'),
    'reauth_required': ('error', '账号需要重新登录'),
    'auth_dead': ('error', '账号登录已失效'),
    'revoked': ('error', '账号会话已被注销'),
}
DELIVERY_BAD = {
    'blocked': ('error', '投递被拒:无发言权限'),
    'failed_permanent': ('error', '投递失败'),
    'dead_letter': ('error', '投递多次失败已放弃'),
    'uncertain': ('warning', '投递结果不确定,需人工确认'),
    'manual_review': ('warning', '投递待人工核查'),
}
ERR_LABELS = {
    'flood_wait': '被 Telegram 限流',
    'transient': '临时网络错误',
    'result_unknown': '发送结果未知',
    'auth_dead': '账号登录失效',
    'permission': '无权限或已被移出群',
    'content_invalid': '消息内容不支持',
    'storage_down': '数据库不可用',
    'cache_down': '缓存不可用',
}
AI_ERR = {
    'provider_not_configured': '未配置模型或 API Key',
    'callback_deadline_exceeded': 'AI 回复超时',
    'idempotent_conflict_unlinked': 'AI 请求重复冲突',
}


def _label(a: TgTelegramAccount | None) -> str:
    if not a:
        return '-'
    if a.username:
        return '@' + a.username
    return a.phone or str(a.telegram_user_id or a.id)


def _ai_reason(err: str | None) -> str:
    if not err:
        return '生成失败'
    if err in AI_ERR:
        return AI_ERR[err]
    if 'http_401' in err or 'http_403' in err:
        return 'API Key 无效或无权限'
    if 'http_429' in err:
        return '模型接口限流/余额不足'
    return err[:160]


class AlertService:
    """异常告警:从账号、路线、投递、AI、租约实时汇总(不单独落表,处理状态由前端按 key+时间记住)。"""

    @staticmethod
    async def _tenants(db: AsyncSession, request: Request) -> set[int] | None:
        if request.user.is_superuser:
            return None
        return {m.tenant_id for m in await membership_dao.get_all(db, user_id=request.user.id)}

    @staticmethod
    async def get_all(*, db: AsyncSession, request: Request) -> list[dict[str, Any]]:
        tenants = await AlertService._tenants(db, request)
        if tenants is not None and not tenants:
            return []
        now = timezone.now()
        since = now - WINDOW

        acc_q = sa.select(TgTelegramAccount).where(TgTelegramAccount.deleted == 0)
        if tenants is not None:
            acc_q = acc_q.where(TgTelegramAccount.tenant_id.in_(tenants))
        accounts = list((await db.execute(acc_q)).scalars())
        by_id = {a.id: a for a in accounts}
        by_uuid = {a.uuid: a for a in accounts}
        alerts: list[dict[str, Any]] = []

        for a in accounts:
            bad = ACCOUNT_BAD.get(a.observed_status)
            if bad:
                alerts.append({
                    'key': f'account:{a.id}:{a.observed_status}',
                    'level': bad[0],
                    'category': 'account',
                    'title': bad[1],
                    'detail': a.last_error or '到「TG 账号」页重新启动,不行就重新导入或验证码登录',
                    'account_label': _label(a),
                    'count': 1,
                    'last_at': a.last_seen_at,
                    'link': '/accounts',
                })

        running = [a for a in accounts if a.desired_status == 'running' and a.observed_status not in ACCOUNT_BAD]
        has_lease = (await db.execute(sa.text("SELECT to_regclass('account_lease') IS NOT NULL"))).scalar()
        if running and has_lease:
            rows = (
                await db.execute(
                    sa.text('SELECT account_id, lease_until FROM account_lease WHERE account_id = ANY(:ids)'),
                    {'ids': [a.uuid for a in running]},
                )
            ).all()
            leases = {r.account_id: r.lease_until for r in rows}
            for a in running:
                until = leases.get(a.uuid)
                if until is not None and until.tzinfo is None:
                    until = until.replace(tzinfo=now.tzinfo)
                if until is None or until < now - HEARTBEAT_GRACE:
                    alerts.append({
                        'key': f'heartbeat:{a.id}',
                        'level': 'error',
                        'category': 'heartbeat',
                        'title': '账号离线:worker 心跳丢失',
                        'detail': '账号设为运行但 worker 没在维持连接,检查 tg-runtime-worker 是否在运行',
                        'account_label': _label(a),
                        'count': 1,
                        'last_at': until,
                        'link': '/accounts',
                    })

        rule_q = sa.select(TgCloneRule).where(TgCloneRule.deleted == 0, TgCloneRule.enabled.is_(True))
        if tenants is not None:
            rule_q = rule_q.where(TgCloneRule.tenant_id.in_(tenants))
        rules = {r.id: r for r in (await db.execute(rule_q)).scalars()}
        targets: list[TgCloneTarget] = []
        if rules:
            targets = list(
                (
                    await db.execute(
                        sa.select(TgCloneTarget).where(
                            TgCloneTarget.rule_id.in_(list(rules)),
                            TgCloneTarget.status == 'active',
                            TgCloneTarget.deleted == 0,
                        )
                    )
                ).scalars()
            )
        health = await route_health(db, targets)
        for t in targets:
            reason = health.get(t.id)
            if not reason:
                continue
            rule = rules[t.rule_id]
            alerts.append({
                'key': f'route:{t.id}:{reason}',
                'level': 'error',
                'category': 'route',
                'title': f'规则「{rule.name}」路线失效',
                'detail': f'{t.source_chat_ref or t.source_chat_id} → {t.target_chat_ref or t.target_chat_id}:{reason}',
                'account_label': _label(by_id.get(rule.account_id)),
                'count': 1,
                'last_at': t.updated_time or t.created_time,
                'link': '/rules',
            })

        uuids = list(by_uuid)
        if uuids:
            rows = (
                await db.execute(
                    sa.select(
                        TgDeliveryJob.account_id,
                        TgDeliveryJob.status,
                        TgDeliveryJob.last_error_class,
                        sa.func.count().label('n'),
                        sa.func.max(TgDeliveryJob.updated_at).label('last_at'),
                    )
                    .where(
                        TgDeliveryJob.account_id.in_(uuids),
                        TgDeliveryJob.status.in_(list(DELIVERY_BAD)),
                        TgDeliveryJob.updated_at >= since,
                    )
                    .group_by(TgDeliveryJob.account_id, TgDeliveryJob.status, TgDeliveryJob.last_error_class)
                )
            ).all()
            for r in rows:
                level, title = DELIVERY_BAD[r.status]
                reason = ERR_LABELS.get(r.last_error_class or '', r.last_error_class or '未知原因')
                alerts.append({
                    'key': f'delivery:{r.account_id}:{r.status}:{r.last_error_class}',
                    'level': level,
                    'category': 'delivery' if r.status not in ('uncertain', 'manual_review') else 'uncertain',
                    'title': title,
                    'detail': f'原因:{reason}(近 24 小时)',
                    'account_label': _label(by_uuid.get(r.account_id)),
                    'count': r.n,
                    'last_at': r.last_at,
                    'link': '/deliveries',
                })

        ai_q = (
            sa.select(
                TgAiBinding.id,
                TgAiBinding.account_id,
                TgAiBinding.chat_id,
                TgAiRun.last_error,
                sa.func.count().label('n'),
                sa.func.max(TgAiRun.updated_time).label('last_at'),
            )
            .join(TgAiConversation, TgAiConversation.id == TgAiRun.conversation_id)
            .join(TgAiBinding, TgAiBinding.id == TgAiConversation.binding_id)
            .where(TgAiRun.status == 'failed', TgAiRun.created_time >= since)
            .group_by(TgAiBinding.id, TgAiBinding.account_id, TgAiBinding.chat_id, TgAiRun.last_error)
        )
        if tenants is not None:
            ai_q = ai_q.where(TgAiRun.tenant_id.in_(tenants))
        for r in (await db.execute(ai_q)).all():
            alerts.append({
                'key': f'ai:{r.id}:{(r.last_error or "")[:40]}',
                'level': 'error',
                'category': 'ai',
                'title': f'AI 炒群调用失败(群 {r.chat_id})',
                'detail': f'原因:{_ai_reason(r.last_error)}(近 24 小时)',
                'account_label': _label(by_id.get(r.account_id)),
                'count': r.n,
                'last_at': r.last_at,
                'link': '/ai-bindings',
            })

        alerts.sort(key=lambda x: x['last_at'] or now - timedelta(days=3650), reverse=True)
        return alerts


alert_service: AlertService = AlertService()

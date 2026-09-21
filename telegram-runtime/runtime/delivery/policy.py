"""SendPolicy: the single gate every Telegram side effect passes through
(§4.3 `SendPolicy.check`, §8.5). Applies uniformly to send/edit/delete —
"create paused but edits still firing" is exactly what this prevents.

Pure decision logic: callers supply live account state, the current policy
snapshot, and the job's approval record. No I/O.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Decision(enum.Enum):
    ALLOW = "allow"
    BLOCKED_POLICY = "blocked_policy"        # global/tenant/project/account/rule off
    BLOCKED_APPROVAL = "blocked_approval"    # required approval absent/stale
    BLOCKED_ACCOUNT = "blocked_account"      # account not send-capable
    BLOCKED_LEASE = "blocked_lease"          # generation/ownership mismatch
    BLOCKED_RATE = "blocked_rate"            # rate limiter / flood window active


class SendState(enum.Enum):
    SENDABLE = "sendable"
    PAUSED = "paused"
    FLOOD_WAIT = "flood_wait"
    AUTH_DEAD = "auth_dead"


@dataclass(frozen=True)
class LiveAccount:
    account_id: str
    generation: int
    send_state: SendState
    flood_wait_until: float | None = None


@dataclass(frozen=True)
class PolicySnapshot:
    """Effective policy evaluated just before the send (§8.5: check at send time,
    not at enqueue). Any level off = off."""

    global_disabled: bool = False
    tenant_disabled: frozenset[str] = frozenset()
    project_disabled: frozenset[str] = frozenset()
    account_disabled: frozenset[str] = frozenset()
    rule_disabled: frozenset[str] = frozenset()
    rate_limit_blocked: frozenset[str] = frozenset()  # route_ids under a limiter wait


@dataclass(frozen=True)
class ApprovalRecord:
    """Immutable approval bound to exact content (§10.1)."""

    approved: bool
    content_hash: str | None
    expires_at: float | None


@dataclass(frozen=True)
class PolicyCheckable:
    """The job/attempt context SendPolicy evaluates."""

    account_id: str
    rule_id: str
    route_id: str
    tenant_id: str
    project_id: str
    expected_generation: int
    requires_approval: bool
    content_hash: str | None


def check(
    job: PolicyCheckable,
    live: LiveAccount,
    policy: PolicySnapshot,
    approval: ApprovalRecord | None,
    *,
    now: float,
) -> Decision:
    if job.account_id != live.account_id:
        return Decision.BLOCKED_LEASE
    if job.expected_generation != live.generation:
        return Decision.BLOCKED_LEASE

    if policy.global_disabled or job.tenant_id in policy.tenant_disabled \
            or job.project_id in policy.project_disabled \
            or job.account_id in policy.account_disabled \
            or job.rule_id in policy.rule_disabled:
        return Decision.BLOCKED_POLICY

    if live.send_state is SendState.PAUSED or live.send_state is SendState.AUTH_DEAD:
        return Decision.BLOCKED_ACCOUNT
    if live.send_state is SendState.FLOOD_WAIT:
        if live.flood_wait_until is None or now < live.flood_wait_until:
            return Decision.BLOCKED_RATE

    if job.route_id in policy.rate_limit_blocked:
        return Decision.BLOCKED_RATE

    if job.requires_approval:
        if approval is None or not approval.approved:
            return Decision.BLOCKED_APPROVAL
        if approval.content_hash is not None and job.content_hash is not None \
                and approval.content_hash != job.content_hash:
            return Decision.BLOCKED_APPROVAL
        if approval.expires_at is not None and now >= approval.expires_at:
            return Decision.BLOCKED_APPROVAL

    return Decision.ALLOW

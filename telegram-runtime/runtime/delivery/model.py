"""Delivery job state machine + error classification (§8.2, §8.3).

Pure transitions: who calls this owns persistence. `transition()` validates the
edge; `classify_error()` maps a send failure to the doc's default action;
`retry_decision()` computes backoff. No I/O.
"""

from __future__ import annotations

import enum
import random
import time
from dataclasses import dataclass


class JobStatus(enum.Enum):
    PENDING = "pending"
    WAITING_APPROVAL = "waiting_approval"
    READY = "ready"
    LEASED = "leased"
    SENDING = "sending"
    SUCCEEDED = "succeeded"
    RETRY_WAIT = "retry_wait"
    BLOCKED = "blocked"
    FAILED_PERMANENT = "failed_permanent"
    DEAD_LETTER = "dead_letter"
    UNCERTAIN = "uncertain"
    RECONCILED_SUCCEEDED = "reconciled_succeeded"
    CONFIRMED_NOT_SENT = "confirmed_not_sent"
    MANUAL_REVIEW = "manual_review"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


TERMINAL: frozenset[JobStatus] = frozenset({
    JobStatus.SUCCEEDED,
    JobStatus.RECONCILED_SUCCEEDED,
    JobStatus.FAILED_PERMANENT,
    JobStatus.DEAD_LETTER,
    JobStatus.MANUAL_REVIEW,
    JobStatus.CANCELLED,
    JobStatus.EXPIRED,
    JobStatus.SUPERSEDED,
})

_UNSENT: frozenset[JobStatus] = frozenset({
    JobStatus.PENDING,
    JobStatus.WAITING_APPROVAL,
    JobStatus.READY,
    JobStatus.RETRY_WAIT,
    JobStatus.BLOCKED,
    JobStatus.UNCERTAIN,
})

# §8.2 legal edges. Anything not listed is a bug, not a transition.
_EDGES: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.WAITING_APPROVAL, JobStatus.READY,
                                  JobStatus.CANCELLED, JobStatus.EXPIRED, JobStatus.SUPERSEDED}),
    JobStatus.WAITING_APPROVAL: frozenset({JobStatus.READY, JobStatus.CANCELLED,
                                           JobStatus.EXPIRED, JobStatus.SUPERSEDED}),
    JobStatus.READY: frozenset({JobStatus.LEASED, JobStatus.BLOCKED,
                                JobStatus.CANCELLED, JobStatus.EXPIRED, JobStatus.SUPERSEDED}),
    JobStatus.LEASED: frozenset({JobStatus.SENDING, JobStatus.READY, JobStatus.BLOCKED,
                                 JobStatus.CANCELLED, JobStatus.EXPIRED, JobStatus.SUPERSEDED}),
    JobStatus.SENDING: frozenset({JobStatus.SUCCEEDED, JobStatus.RETRY_WAIT,
                                  JobStatus.BLOCKED, JobStatus.FAILED_PERMANENT,
                                  JobStatus.DEAD_LETTER, JobStatus.UNCERTAIN,
                                  JobStatus.SUPERSEDED}),
    JobStatus.RETRY_WAIT: frozenset({JobStatus.READY, JobStatus.BLOCKED,
                                     JobStatus.DEAD_LETTER, JobStatus.CANCELLED,
                                     JobStatus.EXPIRED, JobStatus.SUPERSEDED}),
    JobStatus.BLOCKED: frozenset({JobStatus.READY, JobStatus.CANCELLED,
                                  JobStatus.EXPIRED, JobStatus.SUPERSEDED}),
    # uncertain never auto-retries: it exits via reconciliation (§8.4)
    JobStatus.UNCERTAIN: frozenset({JobStatus.RECONCILED_SUCCEEDED,
                                    JobStatus.CONFIRMED_NOT_SENT,
                                    JobStatus.MANUAL_REVIEW, JobStatus.CANCELLED}),
    JobStatus.CONFIRMED_NOT_SENT: frozenset({JobStatus.READY, JobStatus.CANCELLED,
                                             JobStatus.EXPIRED, JobStatus.SUPERSEDED}),
}


class TransitionError(ValueError):
    pass


def can_transition(src: JobStatus, dst: JobStatus) -> bool:
    return dst in _EDGES.get(src, frozenset())


def transition(src: JobStatus, dst: JobStatus) -> JobStatus:
    if not can_transition(src, dst):
        raise TransitionError(f"illegal transition: {src.value} -> {dst.value}")
    return dst


def is_unsent(status: JobStatus) -> bool:
    return status in _UNSENT


class ErrorClass(enum.Enum):
    """§8.3 error taxonomy."""

    FLOOD_WAIT = "flood_wait"             # server-mandated wait (or slow mode)
    TRANSIENT = "transient"               # definitively-not-sent transient error
    RESULT_UNKNOWN = "result_unknown"     # request may have been accepted
    AUTH_DEAD = "auth_dead"               # session revoked / account banned
    PERMISSION_BLOCKED = "permission"     # target permission/topic/protected
    CONTENT_INVALID = "content_invalid"   # unsupported/illegal content
    STORAGE_DOWN = "storage_down"         # postgres unavailable
    CACHE_DOWN = "cache_down"             # redis unavailable


@dataclass(frozen=True)
class ErrorAction:
    """What §8.3 prescribes for an ErrorClass."""

    next_status: JobStatus | None   # None = no per-job transition (worker-level halt)
    worker_halts: bool              # stop claiming new work for this account
    retryable: bool
    flood_wait_until: float | None = None


def classify_error(err: ErrorClass, *, flood_wait_until: float | None = None) -> ErrorAction:
    if err is ErrorClass.FLOOD_WAIT:
        return ErrorAction(JobStatus.RETRY_WAIT, worker_halts=False,
                           retryable=True, flood_wait_until=flood_wait_until)
    if err is ErrorClass.TRANSIENT:
        return ErrorAction(JobStatus.RETRY_WAIT, worker_halts=False, retryable=True)
    if err is ErrorClass.RESULT_UNKNOWN:
        return ErrorAction(JobStatus.UNCERTAIN, worker_halts=False, retryable=False)
    if err is ErrorClass.AUTH_DEAD:
        return ErrorAction(None, worker_halts=True, retryable=False)
    if err is ErrorClass.PERMISSION_BLOCKED:
        return ErrorAction(JobStatus.BLOCKED, worker_halts=False, retryable=False)
    if err is ErrorClass.CONTENT_INVALID:
        return ErrorAction(JobStatus.FAILED_PERMANENT, worker_halts=False, retryable=False)
    if err is ErrorClass.STORAGE_DOWN:
        return ErrorAction(None, worker_halts=True, retryable=False)
    if err is ErrorClass.CACHE_DOWN:
        return ErrorAction(JobStatus.BLOCKED, worker_halts=True, retryable=False)
    raise ValueError(f"unclassified error: {err}")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_s: float = 5.0
    max_delay_s: float = 1800.0
    jitter: float = 0.2


def next_attempt_at(
    policy: RetryPolicy, attempt_no: int, *, now: float | None = None,
    rand: random.Random | None = None,
) -> float | None:
    """Exponential backoff with jitter; None once attempts are exhausted
    (caller then transitions to DEAD_LETTER). Flood waits bypass this policy —
    the server's `flood_wait_until` wins."""
    if attempt_no >= policy.max_attempts:
        return None
    now = time.time() if now is None else now
    rand = rand or random
    delay = min(policy.base_delay_s * (2 ** max(attempt_no - 1, 0)), policy.max_delay_s)
    delay *= 1.0 + rand.uniform(-policy.jitter, policy.jitter)
    return now + max(delay, 0.0)

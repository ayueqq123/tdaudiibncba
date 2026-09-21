"""DeliveryExecutor: one DeliveryPlan -> one DeliveryResult (§4.3, §8).

Wraps the transport (telemirror-derived send paths in production, a fake in
tests) so that one call = one route and results classify into the §8.3
taxonomy. Persistence of results is the caller's job (§6.4 boundary 4).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Protocol

from runtime.planner.model import DeliveryPlan, PlanKind

from .model import ErrorClass
from .policy import ApprovalRecord, LiveAccount, PolicyCheckable, PolicySnapshot, check, Decision


class TransportErrorKind(enum.Enum):
    FLOOD_WAIT = "flood_wait"
    TRANSIENT = "transient"
    RESULT_UNKNOWN = "result_unknown"
    PERMISSION = "permission"
    CONTENT = "content"
    AUTH = "auth"


class TransportError(Exception):
    def __init__(self, kind: TransportErrorKind, detail: str = "",
                 flood_wait_until: float | None = None):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.flood_wait_until = flood_wait_until


class SendTransport(Protocol):
    """The seam to Telethon/telemirror send paths — and to FakeTransport in tests."""

    async def send(self, plan: DeliveryPlan) -> list[int]: ...
    async def edit(self, plan: DeliveryPlan, target_message_id: int) -> None: ...
    async def delete(self, plan: DeliveryPlan, target_message_ids: list[int]) -> None: ...


class ResultStatus(enum.Enum):
    SUCCEEDED = "succeeded"
    RETRYABLE = "retryable"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    POLICY_DENIED = "policy_denied"


@dataclass(frozen=True)
class DeliveryResult:
    """Structured per-route outcome (§4.3). `target_message_ids` keeps the
    per-member album correspondence; partial failures stay visible."""

    plan: DeliveryPlan
    status: ResultStatus
    target_message_ids: tuple[int, ...] = ()
    error_class: ErrorClass | None = None
    error_detail: str | None = None
    flood_wait_until: float | None = None
    decision: Decision | None = None


_ERROR_CLASS_MAP = {
    TransportErrorKind.FLOOD_WAIT: ErrorClass.FLOOD_WAIT,
    TransportErrorKind.TRANSIENT: ErrorClass.TRANSIENT,
    TransportErrorKind.RESULT_UNKNOWN: ErrorClass.RESULT_UNKNOWN,
    TransportErrorKind.PERMISSION: ErrorClass.PERMISSION_BLOCKED,
    TransportErrorKind.CONTENT: ErrorClass.CONTENT_INVALID,
    TransportErrorKind.AUTH: ErrorClass.AUTH_DEAD,
}


class DeliveryExecutor:
    def __init__(self, transport: SendTransport):
        self._transport = transport

    async def execute(
        self,
        plan: DeliveryPlan,
        *,
        live: LiveAccount,
        policy: PolicySnapshot,
        approval: ApprovalRecord | None,
        expected_generation: int,
        tenant_id: str,
        project_id: str,
        now: float,
        target_message_ids: list[int] | None = None,
    ) -> DeliveryResult:
        decision = check(
            PolicyCheckable(
                account_id=plan.account_id, rule_id=plan.rule_id, route_id=plan.route_id,
                tenant_id=tenant_id, project_id=project_id,
                expected_generation=expected_generation,
                requires_approval=plan.requires_approval, content_hash=plan.payload_hash,
            ),
            live, policy, approval, now=now,
        )
        if decision is not Decision.ALLOW:
            return DeliveryResult(plan=plan, status=ResultStatus.POLICY_DENIED, decision=decision)

        try:
            if plan.kind is PlanKind.SEND:
                ids = await self._transport.send(plan)
                return DeliveryResult(plan=plan, status=ResultStatus.SUCCEEDED,
                                      target_message_ids=tuple(ids), decision=decision)
            if plan.kind is PlanKind.EDIT:
                if not target_message_ids:
                    raise ValueError("EDIT plan requires target_message_ids")
                await self._transport.edit(plan, target_message_ids[0])
                return DeliveryResult(plan=plan, status=ResultStatus.SUCCEEDED,
                                      target_message_ids=tuple(target_message_ids), decision=decision)
            if plan.kind in (PlanKind.DELETE, PlanKind.TOMBSTONE):
                await self._transport.delete(plan, target_message_ids or [])
                return DeliveryResult(plan=plan, status=ResultStatus.SUCCEEDED,
                                      target_message_ids=tuple(target_message_ids or ()),
                                      decision=decision)
            raise ValueError(f"unknown plan kind: {plan.kind}")
        except TransportError as exc:
            err_class = _ERROR_CLASS_MAP[exc.kind]
            status = {
                ErrorClass.FLOOD_WAIT: ResultStatus.RETRYABLE,
                ErrorClass.TRANSIENT: ResultStatus.RETRYABLE,
                ErrorClass.PERMISSION_BLOCKED: ResultStatus.BLOCKED,
                ErrorClass.CONTENT_INVALID: ResultStatus.FAILED,
                ErrorClass.RESULT_UNKNOWN: ResultStatus.UNCERTAIN,
                ErrorClass.AUTH_DEAD: ResultStatus.FAILED,
            }[err_class]
            return DeliveryResult(plan=plan, status=status, error_class=err_class,
                                  error_detail=exc.detail,
                                  flood_wait_until=exc.flood_wait_until,
                                  decision=decision)

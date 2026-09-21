"""Tests for SendPolicy gate + DeliveryExecutor with a fake transport."""

import asyncio

import pytest

from runtime.delivery.executor import (
    DeliveryExecutor,
    DeliveryResult,
    ResultStatus,
    TransportError,
    TransportErrorKind,
)
from runtime.delivery.model import ErrorClass
from runtime.delivery.policy import (
    ApprovalRecord,
    Decision,
    LiveAccount,
    PolicySnapshot,
    SendState,
    check,
)
from runtime.planner.model import (
    CloneMode,
    DeliveryPlan,
    PlanKind,
)
from runtime.delivery.policy import PolicyCheckable


def _job(**kw):
    base = dict(account_id="a1", rule_id="r1", route_id="rt1", tenant_id="t1",
                project_id="p1", expected_generation=5, requires_approval=False,
                content_hash="h1")
    base.update(kw)
    return PolicyCheckable(**base)


def _live(**kw):
    base = dict(account_id="a1", generation=5, send_state=SendState.SENDABLE)
    base.update(kw)
    return LiveAccount(**base)


def test_allow_default():
    assert check(_job(), _live(), PolicySnapshot(), None, now=0.0) is Decision.ALLOW


def test_generation_and_account_mismatch_blocked():
    assert check(_job(expected_generation=4), _live(), PolicySnapshot(), None,
                 now=0.0) is Decision.BLOCKED_LEASE
    assert check(_job(account_id="other"), _live(), PolicySnapshot(), None,
                 now=0.0) is Decision.BLOCKED_LEASE


def test_policy_levels():
    assert check(_job(), _live(), PolicySnapshot(global_disabled=True), None, now=0.0) \
        is Decision.BLOCKED_POLICY
    assert check(_job(), _live(), PolicySnapshot(tenant_disabled=frozenset({"t1"})), None, now=0.0) \
        is Decision.BLOCKED_POLICY
    assert check(_job(), _live(), PolicySnapshot(rule_disabled=frozenset({"r1"})), None, now=0.0) \
        is Decision.BLOCKED_POLICY
    assert check(_job(), _live(), PolicySnapshot(rule_disabled=frozenset({"other"})), None, now=0.0) \
        is Decision.ALLOW


def test_account_states():
    assert check(_job(), _live(send_state=SendState.PAUSED), PolicySnapshot(), None, now=0.0) \
        is Decision.BLOCKED_ACCOUNT
    assert check(_job(), _live(send_state=SendState.AUTH_DEAD), PolicySnapshot(), None, now=0.0) \
        is Decision.BLOCKED_ACCOUNT
    flood = _live(send_state=SendState.FLOOD_WAIT, flood_wait_until=100.0)
    assert check(_job(), flood, PolicySnapshot(), None, now=50.0) is Decision.BLOCKED_RATE
    assert check(_job(), flood, PolicySnapshot(), None, now=150.0) is Decision.ALLOW


def test_approval_binding():
    job = _job(requires_approval=True, content_hash="h1")
    assert check(job, _live(), PolicySnapshot(), None, now=0.0) is Decision.BLOCKED_APPROVAL
    bad_hash = ApprovalRecord(approved=True, content_hash="other", expires_at=None)
    assert check(job, _live(), PolicySnapshot(), bad_hash, now=0.0) is Decision.BLOCKED_APPROVAL
    expired = ApprovalRecord(approved=True, content_hash="h1", expires_at=10.0)
    assert check(job, _live(), PolicySnapshot(), expired, now=20.0) is Decision.BLOCKED_APPROVAL
    ok = ApprovalRecord(approved=True, content_hash="h1", expires_at=10.0)
    assert check(job, _live(), PolicySnapshot(), ok, now=5.0) is Decision.ALLOW


class FakeTransport:
    def __init__(self, send_result=None, send_exc=None):
        self.send_result = send_result or [5001]
        self.send_exc = send_exc
        self.calls = []

    async def send(self, plan):
        self.calls.append(("send", plan.route_id))
        if self.send_exc:
            raise self.send_exc
        return self.send_result

    async def edit(self, plan, target_message_id):
        self.calls.append(("edit", plan.route_id, target_message_id))

    async def delete(self, plan, ids):
        self.calls.append(("delete", plan.route_id, tuple(ids)))


def _plan(kind=PlanKind.SEND, requires_approval=False):
    return DeliveryPlan(
        kind=kind, rule_id="r1", rule_version=1, route_id="rt1", account_id="a1",
        source_scope="peer", source_chat_id=100, source_message_id=1, revision=1,
        target_chat_id=200, target_topic_id=None, mode=CloneMode.COPY,
        payload_ref="ref", payload_hash="h1", requires_approval=requires_approval,
    )


def _exec_kwargs(**kw):
    base = dict(live=_live(), policy=PolicySnapshot(), approval=None,
                expected_generation=5, tenant_id="t1", project_id="p1", now=0.0)
    base.update(kw)
    return base


def test_executor_send_success():
    t = FakeTransport(send_result=[5001, 5002])
    r = asyncio.run(DeliveryExecutor(t).execute(_plan(), **_exec_kwargs()))
    assert r.status is ResultStatus.SUCCEEDED
    assert r.target_message_ids == (5001, 5002)
    assert t.calls == [("send", "rt1")]


def test_executor_policy_denied_no_transport_call():
    t = FakeTransport()
    r = asyncio.run(DeliveryExecutor(t).execute(
        _plan(requires_approval=True), **_exec_kwargs(approval=None)))
    assert r.status is ResultStatus.POLICY_DENIED
    assert r.decision is Decision.BLOCKED_APPROVAL
    assert t.calls == []


def test_executor_flood_wait_retryable():
    t = FakeTransport(send_exc=TransportError(TransportErrorKind.FLOOD_WAIT,
                                              "slow", flood_wait_until=3600.0))
    r = asyncio.run(DeliveryExecutor(t).execute(_plan(), **_exec_kwargs()))
    assert r.status is ResultStatus.RETRYABLE
    assert r.error_class is ErrorClass.FLOOD_WAIT and r.flood_wait_until == 3600.0


def test_executor_result_unknown_uncertain():
    t = FakeTransport(send_exc=TransportError(TransportErrorKind.RESULT_UNKNOWN))
    r = asyncio.run(DeliveryExecutor(t).execute(_plan(), **_exec_kwargs()))
    assert r.status is ResultStatus.UNCERTAIN
    assert r.error_class is ErrorClass.RESULT_UNKNOWN


def test_executor_permission_blocked():
    t = FakeTransport(send_exc=TransportError(TransportErrorKind.PERMISSION))
    r = asyncio.run(DeliveryExecutor(t).execute(_plan(), **_exec_kwargs()))
    assert r.status is ResultStatus.BLOCKED
    assert r.error_class is ErrorClass.PERMISSION_BLOCKED


def test_executor_edit_and_delete():
    t = FakeTransport()
    asyncio.run(DeliveryExecutor(t).execute(
        _plan(kind=PlanKind.EDIT), target_message_ids=[9001], **_exec_kwargs()))
    asyncio.run(DeliveryExecutor(t).execute(
        _plan(kind=PlanKind.DELETE), target_message_ids=[9001], **_exec_kwargs()))
    assert t.calls == [("edit", "rt1", 9001), ("delete", "rt1", (9001,))]

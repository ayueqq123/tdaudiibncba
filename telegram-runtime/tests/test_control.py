"""RuntimeController transitions + heartbeat lease semantics."""

from collections import OrderedDict
from types import SimpleNamespace

import httpx
import pytest

from runtime.account.lease_heartbeat import HeartbeatState, LeaseHeartbeat
from runtime.control.controller import (
    AccountPhase,
    CommandStatus,
    CommandType,
    RuntimeCommand,
    RuntimeController,
)
from runtime.ingest.normalizer import ChatClass
from runtime.worker import live
from runtime.worker.control_client import ControlClient


def cmd(t, account="a1", **kw):
    return RuntimeCommand(account_id=account, type=t, **kw)


def test_start_stop_cycle():
    c = RuntimeController()
    r = c.apply(cmd(CommandType.START))
    assert r.accepted and r.state.phase is AccountPhase.STARTING
    c.mark_online("a1", worker_id="w1", generation=7)
    assert c.current("a1").generation == 7
    r = c.apply(cmd(CommandType.STOP))
    assert r.accepted and r.state.phase is AccountPhase.STOPPING
    c.mark_stopped("a1")
    assert c.current("a1").phase is AccountPhase.STOPPED


def test_pause_resume_only_when_online():
    c = RuntimeController()
    assert c.apply(cmd(CommandType.PAUSE)).status is CommandStatus.REJECTED
    c.apply(cmd(CommandType.START))
    c.mark_online("a1", worker_id="w1", generation=1)
    assert c.apply(cmd(CommandType.PAUSE)).accepted
    assert c.apply(cmd(CommandType.RESUME)).accepted


def test_dedup_replay():
    c = RuntimeController()
    first = c.apply(cmd(CommandType.START, dedup_key="op-1"))
    replay = c.apply(cmd(CommandType.START, dedup_key="op-1"))
    assert first.accepted and replay.status is CommandStatus.DUPLICATE
    # replay returns current state, no double transition
    assert replay.state.phase is AccountPhase.STARTING


def test_illegal_transition_rejected_not_thrown():
    c = RuntimeController()
    r = c.apply(cmd(CommandType.RESUME))  # stopped account
    assert r.status is CommandStatus.REJECTED
    assert "illegal" in r.reason


def test_revoke_and_disable():
    c = RuntimeController()
    c.apply(cmd(CommandType.START))
    c.mark_online("a1", worker_id="w1", generation=1)
    assert c.apply(cmd(CommandType.MARK_REVOKED)).state.phase is AccountPhase.REVOKED
    assert c.apply(cmd(CommandType.START)).status is CommandStatus.REJECTED
    assert c.apply(cmd(CommandType.DISABLE)).state.phase is AccountPhase.DISABLED


def test_takeover_requires_confirmed_death():
    c = RuntimeController()
    c.apply(cmd(CommandType.START))
    c.mark_online("a1", worker_id="w-old", generation=5)
    # unconfirmed: blocked, never silently takes over (§5.3)
    r = c.apply(cmd(CommandType.TAKEOVER, issued_by="w-new"))
    assert r.status is CommandStatus.REJECTED
    assert c.current("a1").phase is AccountPhase.TAKEOVER_BLOCKED
    # confirmed dead: takeover bumps generation
    r = c.apply(cmd(CommandType.TAKEOVER, issued_by="w-new",
                    old_holder_confirmed_dead=True))
    assert r.accepted and r.state.generation == 6
    assert r.state.worker_id == "w-new"


@pytest.mark.asyncio
async def test_heartbeat_renews_and_stops():
    calls = []

    async def renew():
        calls.append(1)
        return True

    slept = []

    async def fake_sleep(t):
        slept.append(t)
        hb.stop()

    hb = LeaseHeartbeat(renew, interval_s=10, sleep=fake_sleep)
    state = await hb.run()
    assert state is HeartbeatState.STOPPED and hb.renew_count == 1
    assert slept == [10]


@pytest.mark.asyncio
async def test_heartbeat_lost_triggers_callback():
    lost = []

    async def renew():
        return False

    hb = LeaseHeartbeat(renew, on_lost=lost.append)
    state = await hb.run()
    assert state is HeartbeatState.LOST and lost == ["lease_lost"]


@pytest.mark.asyncio
async def test_heartbeat_renew_error_is_lost():
    lost = []

    async def renew():
        raise ConnectionError("pg down")

    hb = LeaseHeartbeat(renew, on_lost=lost.append)
    await hb.run()
    assert hb.state is HeartbeatState.LOST
    assert lost[0].startswith("renew_error:")


@pytest.fixture
def ai_event_claims(monkeypatch):
    monkeypatch.setattr(live, "_AI_EVENT_CLAIMED", OrderedDict())


def _ai_event():
    event = SimpleNamespace(message=SimpleNamespace(message="hello", sender=None))
    raw = SimpleNamespace(
        chat_id=100, message_id=200, sender_id=300,
        topic_id=None, reply_to_message_id=None,
        chat_class=ChatClass.BROADCAST, sender_is_bot=False,
    )
    return event, raw


class FakeControl:
    def __init__(self, fail_first=False):
        self.calls = []
        self.fail_first = fail_first

    async def notify_ai_event(self, payload):
        self.calls.append(payload)
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("control unavailable")


@pytest.mark.asyncio
async def test_ai_event_deduplicates_by_tenant_project_chat_message(ai_event_claims):
    event, raw = _ai_event()
    control = FakeControl()

    await live._report_ai_event(event, raw, control, 7, "tenant-a", "project-a")
    await live._report_ai_event(event, raw, control, 8, "tenant-a", "project-a")
    await live._report_ai_event(event, raw, control, 7, "tenant-a", "project-b")

    assert len(control.calls) == 2
    assert control.calls[0]["api_row_id"] == 7
    assert control.calls[1]["api_row_id"] == 7


@pytest.mark.asyncio
async def test_ai_event_failed_notify_can_retry(ai_event_claims):
    event, raw = _ai_event()
    control = FakeControl(fail_first=True)

    await live._report_ai_event(event, raw, control, 7, "tenant-a", "project-a")
    await live._report_ai_event(event, raw, control, 8, "tenant-a", "project-a")

    assert [call["api_row_id"] for call in control.calls] == [7, 8]


@pytest.mark.asyncio
async def test_control_client_routes_ai_events_to_separate_pool():
    requests = {"main": [], "ai": []}

    def transport(name):
        def handle(request):
            requests[name].append(request.url.path)
            return httpx.Response(200, json={"data": {}})
        return httpx.MockTransport(handle)

    client = ControlClient("https://control.example", "token")
    await client.close()
    client._http = httpx.AsyncClient(
        base_url="https://control.example", transport=transport("main"))
    client._ai_http = httpx.AsyncClient(
        base_url="https://control.example", transport=transport("ai"))
    try:
        await client.notify_ai_event({"message_id": 1})
        await client.clone_transform("rule", "hello")
    finally:
        await client.close()

    assert requests == {
        "main": ["/ai/clone_transform"],
        "ai": ["/ai/event"],
    }

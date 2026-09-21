"""RuntimeController transitions + heartbeat lease semantics."""

import pytest

from runtime.account.lease_heartbeat import HeartbeatState, LeaseHeartbeat
from runtime.control.controller import (
    AccountPhase,
    CommandStatus,
    CommandType,
    RuntimeCommand,
    RuntimeController,
)


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

"""Worker host loop: reconcile/lease/commands/candidate resolution.

Telethon stays out of the loop — sessions and transports are faked at the
connector/router seam; sqlite exercises the real repos."""

import hashlib

import pytest
import pytest_asyncio
from sqlalchemy import select

from runtime.delivery.executor import TransportError
from runtime.storage.db import create_schema, make_engine, make_session_factory
from runtime.storage.models import AccountLease, DeliveryJob
from runtime.worker.control_client import (
    Assignment,
    CandidatePayload,
    PendingCommand,
    SessionBundle,
)
from runtime.worker.host import WorkerHostMain
from runtime.worker.live import PayloadResolver
from runtime.worker.runner import plan_from_job


class FakeClient:
    def __init__(self):
        self.handlers = []

    def add_event_handler(self, fn, ev):
        self.handlers.append((fn, ev))

    async def get_dialogs(self):
        return []


class FakeSession:
    def __init__(self):
        self.client = FakeClient()
        self.closed = False

    async def close(self):
        self.closed = True


class FakeControl:
    def __init__(self):
        self.accounts: list[Assignment] = []
        self.sessions: dict[str, SessionBundle] = {}
        self.commands: dict[int, list[PendingCommand]] = {}
        self.acks: list[tuple[int, str, str]] = []
        self.candidates: dict[str, CandidatePayload] = {}

    async def list_accounts(self):
        return self.accounts

    async def fetch_session(self, uuid):
        return self.sessions[uuid]

    async def pull_rules(self, api_row_id):
        return [{
            'rule_id': 7, 'version': 3,
            'snapshot': {
                'rule': {'id': 7, 'account_id': 5, 'mode': 'copy'},
                'targets': [{'route_id': 'rt1', 'source_chat_id': 100,
                             'target_chat_id': 200, 'filters': {}}],
            },
        }]

    async def pull_commands(self, api_row_id):
        return self.commands.get(api_row_id, [])

    async def ack_command(self, command_id, status, result=""):
        self.acks.append((command_id, status, result))

    async def get_candidate(self, uuid):
        return self.candidates[uuid]


@pytest_asyncio.fixture()
async def factory(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await create_schema(engine)
    yield make_session_factory(engine)
    await engine.dispose()


def _assignment(account_id="acct-1"):
    return Assignment(account_id=account_id, api_row_id=5,
                      tenant_id="tu", project_id="pu",
                      telegram_user_id=999, observed_status="verified",
                      has_session=True)


async def _connect(bundle):
    return FakeSession()


def _bundle():
    return SessionBundle(session_bytes=b"x", api_id=1, api_hash="h")


async def test_assign_heartbeat_release(factory):
    control = FakeControl()
    control.accounts.append(_assignment())
    control.sessions["acct-1"] = _bundle()
    host = WorkerHostMain(
        "w1", factory, control,  # type: ignore[arg-type]
        session_connector=_connect)  # type: ignore[arg-type]
    await host.tick()
    assert "acct-1" in host._runner_host.runners
    hosted = host._hosted["acct-1"]
    assert hosted.heartbeat_task is not None
    async with factory() as s:
        lease = (await s.execute(
            select(AccountLease).where(
                AccountLease.account_id == "acct-1"))).scalar_one()
        assert lease.worker_id == "w1" and lease.generation == 1
    # rules got cached from control pull; one target -> two scope variants
    snaps = host._rules_cache["acct-1"]
    assert len(snaps) == 2
    assert {s.source_scope for s in snaps} == {
        "peer:100", "peer:100:acct:acct-1"}
    assert snaps[0].rule_id == "7" and snaps[0].version == 3

    # desired disappears -> release
    control.accounts.clear()
    await host.tick()
    assert "acct-1" not in host._runner_host.runners
    assert hosted.session.closed


async def test_lease_lost_releases_account(factory):
    control = FakeControl()
    control.accounts.append(_assignment())
    control.sessions["acct-1"] = _bundle()
    host = WorkerHostMain(
        "w1", factory, control,  # type: ignore[arg-type]
        session_connector=_connect)  # type: ignore[arg-type]
    await host.tick()
    # someone else takes the lease (w1's row expired first)
    async with factory() as s:
        import datetime as _dt

        from sqlalchemy import update

        from runtime.storage.models import AccountLease
        from runtime.storage.repos import LeaseRepository
        await s.execute(update(AccountLease).values(
            lease_until=_dt.datetime.now(_dt.timezone.utc)
            - _dt.timedelta(seconds=1)))
        await s.commit()
        gen = await LeaseRepository(s).acquire("acct-1", "w2")
        assert gen == 2
    host._hosted["acct-1"].heartbeat.stop()
    host._lost.add("acct-1")   # what on_lost does
    await host.tick()
    assert "acct-1" not in host._hosted


async def test_stop_command_releases_and_acks(factory):
    control = FakeControl()
    control.accounts.append(_assignment())
    control.sessions["acct-1"] = _bundle()
    host = WorkerHostMain(
        "w1", factory, control,  # type: ignore[arg-type]
        session_connector=_connect)  # type: ignore[arg-type]
    await host.tick()
    control.commands[5] = [PendingCommand(
        id=41, type="StopAccount", dedup_key="k1")]
    await host.poll_commands()
    assert (41, "done", "released") in control.acks
    assert "acct-1" not in host._hosted


async def test_candidate_payload_resolution(factory):
    control = FakeControl()
    body = "回复文本"
    digest = hashlib.sha256(body.encode()).hexdigest()
    control.candidates["c1"] = CandidatePayload(
        content=body, content_hash=digest, status="approved")
    resolver = PayloadResolver(control)  # type: ignore[arg-type]
    assert await resolver.candidate_text("c1", digest) == body
    with pytest.raises(TransportError):
        await resolver.candidate_text("c1", "0" * 64)
    control.candidates["c2"] = CandidatePayload(
        content=body, content_hash=digest, status="pending")
    with pytest.raises(TransportError):
        await resolver.candidate_text("c2", digest)


def test_plan_from_job_send_message_alias():
    job = DeliveryJob(
        id="j1", tenant_id="t", project_id="p",
        idempotency_key="k", kind="send_message",
        route_id="r", rule_id="rl", rule_version=1, account_id="a",
        source_scope="s", source_chat_id=1, source_message_id=2,
        revision=1, target_chat_id=3, mode="copy", status="ready")
    assert plan_from_job(job).kind.value == "send"

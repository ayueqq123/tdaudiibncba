"""A3 end-to-end: inbox event -> plan -> job -> claim -> policy -> transport ->
record. sqlite + FakeTransport, no real network."""

import io

import pytest
import pytest_asyncio
from sqlalchemy import select, update
from telethon import utils
from telethon.tl import types

from runtime.delivery.executor import (
    DeliveryExecutor,
    TransportError,
    TransportErrorKind,
)
from runtime.delivery.model import ErrorClass, RetryPolicy
from runtime.delivery.policy import LiveAccount, PolicySnapshot, SendState
from runtime.ingest.normalizer import ChatClass, EventNormalizer, RawUpdate
from runtime.planner.model import (
    ApprovalPolicy,
    CloneMode,
    DeliveryPlan,
    EventKind,
    RuleSnapshot,
    RouteTarget,
)
from runtime.storage.db import create_schema, make_engine, make_session_factory
from runtime.storage.models import (
    DeliveryAttempt,
    DeliveryJob,
    EventInbox,
    MessageMap,
)
from runtime.storage.repos import EventInboxRepository
from runtime.worker.runner import AccountRunner, RunnerDeps, WorkerHost
from runtime.worker.live import _sniff_media_bytes


class FakeTransport:
    def __init__(self, result=9000, error: TransportError | None = None,
                 album_ids: list[int] | None = None,
                 resolve_error: TransportError | None = None):
        self.result = result
        self.error = error
        self.album_ids = album_ids
        self.resolve_error = resolve_error
        self.sent: list[DeliveryPlan] = []
        self.resolved: list[DeliveryPlan] = []
        self.albums: list[list[DeliveryPlan]] = []

    async def send(self, plan):
        if self.error:
            raise self.error
        self.sent.append(plan)
        return [self.result]

    async def resolve_album(self, plan):
        self.resolved.append(plan)
        if self.resolve_error:
            raise self.resolve_error
        return (self.album_ids if self.album_ids is not None
                else [plan.source_message_id])

    async def send_album(self, plans):
        if self.error:
            raise self.error
        self.albums.append(list(plans))
        return [self.result + index for index, _ in enumerate(plans)]

    async def edit(self, plan, target_message_id):
        return None

    async def delete(self, plan, target_message_ids):
        return None


@pytest_asyncio.fixture()
async def factory(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await create_schema(engine)
    yield make_session_factory(engine)
    await engine.dispose()


def _rules(account="a1"):
    return [RuleSnapshot(
        rule_id="r1", version=1, account_id=account,
        source_scope="peer:100", source_chat_id=100, source_topic_id=None,
        targets=(RouteTarget(route_id="rt1", target_chat_id=200,
                            target_topic_id=None),),
        mode=CloneMode.COPY, sync_edit=True, sync_delete=True,
        approval_policy=ApprovalPolicy.RULE_AUTHORIZED)]


def _deps(factory, transport=None, **over):
    d = RunnerDeps(
        session_factory=factory,
        executor=DeliveryExecutor(transport or FakeTransport()),
        rules=_rules,
        live=lambda a: LiveAccount(a, generation=1,
                                   send_state=SendState.SENDABLE),
        policy=lambda: PolicySnapshot(),
        tenant_id="t", project_id="p",
    )
    for k, v in over.items():
        setattr(d, k, v)
    return d


async def _ingest(factory, msg=1, kind=EventKind.CREATE, grouped_id=None):
    raw = RawUpdate(kind=kind, chat_id=100, message_id=msg,
                    chat_class=ChatClass.BROADCAST, grouped_id=grouped_id)
    ev = EventNormalizer().normalize(raw, "a1")
    async with factory() as s:
        assert await EventInboxRepository(s).ingest(ev, tenant_id="t",
                                                  project_id="p")


async def _album_runner(factory, transport, message_ids):
    for message_id in message_ids:
        await _ingest(factory, msg=message_id, grouped_id=77)
    runner = AccountRunner("a1", 1, _deps(factory, transport))
    await runner.drain_inbox()
    async with factory() as s:
        await s.execute(update(DeliveryJob).values(next_attempt_at=None))
        await s.commit()
    return runner


async def _job(factory):
    async with factory() as s:
        return (await s.execute(select(DeliveryJob))).scalars().first()


async def test_e2e_send_success_writes_mapping(factory):
    await _ingest(factory)
    runner = AccountRunner("a1", 1, _deps(factory))
    await runner.run_once()

    job = await _job(factory)
    assert job.status == "succeeded" and job.attempt_count == 1
    async with factory() as s:
        m = (await s.execute(select(MessageMap))).scalar_one()
        assert m.target_message_id == 9000 and m.route_id == "rt1"
        att = (await s.execute(select(DeliveryAttempt))).scalar_one()
        assert att.result_status == "succeeded" and att.finished_at
        inbox = (await s.execute(select(EventInbox))).scalar_one()
        assert inbox.processed is True


async def test_album_resolution_sends_missing_members_and_records_mappings(factory):
    transport = FakeTransport(album_ids=[1, 2, 3])
    runner = await _album_runner(factory, transport, [1, 3])

    assert await runner.send_next() is not None

    assert len(transport.albums) == 1
    assert [p.source_message_id for p in transport.albums[0]] == [1, 2, 3]
    async with factory() as s:
        mappings = (await s.execute(
            select(MessageMap).order_by(MessageMap.source_message_id)
        )).scalars().all()
        assert [m.source_message_id for m in mappings] == [1, 2, 3]
        jobs = (await s.execute(
            select(DeliveryJob).order_by(DeliveryJob.source_message_id)
        )).scalars().all()
        assert [j.status for j in jobs] == ["succeeded", "succeeded"]


async def test_claimed_album_sibling_missing_from_resolution_is_sent_and_recorded(
    factory,
):
    class MissingSiblingTransport(FakeTransport):
        async def resolve_album(self, plan):
            self.resolved.append(plan)
            return sorted({plan.source_message_id, 2})

    transport = MissingSiblingTransport()
    runner = await _album_runner(factory, transport, [1, 3])

    assert await runner.send_next() is not None

    assert len(transport.albums) == 1
    assert [p.source_message_id for p in transport.albums[0]] == [1, 2, 3]
    async with factory() as s:
        mappings = (await s.execute(
            select(MessageMap).order_by(MessageMap.source_message_id)
        )).scalars().all()
        assert [m.source_message_id for m in mappings] == [1, 2, 3]
        jobs = (await s.execute(
            select(DeliveryJob).order_by(DeliveryJob.source_message_id)
        )).scalars().all()
        assert [j.status for j in jobs] == ["succeeded", "succeeded"]


async def test_late_album_sibling_uses_existing_mapping_without_transport(factory):
    transport = FakeTransport(album_ids=[1, 2, 3])
    runner = await _album_runner(factory, transport, [1])
    await runner.send_next()
    assert len(transport.albums) == 1

    await _ingest(factory, msg=2, grouped_id=77)
    await runner.drain_inbox()
    async with factory() as s:
        await s.execute(
            update(DeliveryJob)
            .where(DeliveryJob.source_message_id == 2)
            .values(next_attempt_at=None)
        )
        await s.commit()

    await runner.send_next()

    assert len(transport.resolved) == 1
    assert len(transport.albums) == 1
    assert transport.sent == []
    async with factory() as s:
        late_job = (await s.execute(
            select(DeliveryJob).where(DeliveryJob.source_message_id == 2)
        )).scalar_one()
        assert late_job.status == "succeeded"


async def test_album_resolution_transient_error_retries_without_sending(factory):
    err = TransportError(TransportErrorKind.TRANSIENT, "album fetch failed")
    transport = FakeTransport(album_ids=[1, 2, 3], resolve_error=err)
    runner = await _album_runner(factory, transport, [1])

    await runner.send_next()

    job = await _job(factory)
    assert job.status == "retry_wait"
    assert job.last_error_class == ErrorClass.TRANSIENT.value
    assert len(transport.resolved) == 1
    assert transport.albums == []
    assert transport.sent == []


def test_mp4_sniffing_preserves_video_media_type():
    extension, mime_type = _sniff_media_bytes(b"\x00\x00\x00\x18ftypisom")
    assert (extension, mime_type) == (".mp4", "video/mp4")

    file = io.BytesIO(b"\x00\x00\x00\x18ftypisom")
    file.name = f"media{extension}"
    attributes, detected_mime = utils.get_attributes(file)
    assert detected_mime == "video/mp4"
    assert any(isinstance(attr, types.DocumentAttributeVideo)
               for attr in attributes)


async def test_drain_is_idempotent_on_replay(factory):
    await _ingest(factory)
    runner = AccountRunner("a1", 1, _deps(factory))
    await runner.run_once()
    # re-ingest the same event: dedup blocks inbox; no second job
    raw = RawUpdate(kind=EventKind.CREATE, chat_id=100, message_id=1,
                    chat_class=ChatClass.BROADCAST)
    ev = EventNormalizer().normalize(raw, "a1")
    async with factory() as s:
        assert await EventInboxRepository(s).ingest(ev, tenant_id="t",
                                                  project_id="p") is False
    await runner.run_once()
    async with factory() as s:
        assert len((await s.execute(select(DeliveryJob))).scalars().all()) == 1


async def test_flood_wait_pauses_until_server_until(factory):
    err = TransportError(TransportErrorKind.FLOOD_WAIT, "slow",
                         flood_wait_until=2_000_000_000)
    await _ingest(factory)
    runner = AccountRunner("a1", 1, _deps(factory, FakeTransport(error=err)))
    await runner.run_once()
    job = await _job(factory)
    assert job.status == "retry_wait" and job.flood_wait_until is not None
    # flood window not elapsed: next claim skips it
    assert await runner.send_next() is None


async def test_transient_retry_then_dead_letter(factory):
    err = TransportError(TransportErrorKind.TRANSIENT, "conn reset")
    deps = _deps(factory, FakeTransport(error=err),
                 retry_policy=RetryPolicy(max_attempts=1))
    await _ingest(factory)
    runner = AccountRunner("a1", 1, deps)
    await runner.run_once()
    job = await _job(factory)
    assert job.status == "dead_letter" \
        and job.last_error_class == ErrorClass.TRANSIENT.value


async def test_uncertain_never_blind_retried(factory):
    err = TransportError(TransportErrorKind.RESULT_UNKNOWN, "timeout?")
    await _ingest(factory)
    runner = AccountRunner("a1", 1, _deps(factory, FakeTransport(error=err)))
    await runner.run_once()
    job = await _job(factory)
    assert job.status == "uncertain" \
        and job.last_error_class == ErrorClass.RESULT_UNKNOWN.value
    # uncertain is not re-claimable; exits only via reconciliation
    assert await runner.send_next() is None


async def test_policy_block_marks_job_blocked(factory):
    deps = _deps(factory, policy=lambda: PolicySnapshot(
        rule_disabled=frozenset({"r1"})))
    await _ingest(factory)
    runner = AccountRunner("a1", 1, deps)
    await runner.run_once()
    assert (await _job(factory)).status == "blocked"


async def test_wrong_generation_releases_and_halts(factory):
    deps = _deps(factory, live=lambda a: LiveAccount(
        a, generation=99, send_state=SendState.SENDABLE))
    await _ingest(factory)
    runner = AccountRunner("a1", 1, deps)
    await runner.run_once()
    job = await _job(factory)
    assert runner.halted == "lease_lost"
    assert job.status == "ready"  # released for the real owner


async def test_auth_dead_halts_runner(factory):
    err = TransportError(TransportErrorKind.AUTH, "session revoked")
    await _ingest(factory)
    runner = AccountRunner("a1", 1, _deps(factory, FakeTransport(error=err)))
    await runner.run_once()
    assert runner.halted == ErrorClass.AUTH_DEAD.value
    assert (await _job(factory)).status == "failed_permanent"


async def test_host_isolates_accounts(factory):
    ok = _deps(factory)
    host = WorkerHost("w1", ok)
    r1 = await host.assign("a1", 1)
    r2 = await host.assign("a2", 1)
    r1.halted = "auth_dead"
    assert host.runners["a2"].halted is None
    host.release("a1")
    assert "a1" not in host.runners and "a2" in host.runners

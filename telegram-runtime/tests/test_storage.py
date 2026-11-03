"""runtime/storage repo tests on sqlite (same code path as Postgres)."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from runtime.ingest.normalizer import ChatClass, EventNormalizer, RawUpdate
from runtime.planner.model import (
    CloneMode,
    DeliveryPlan,
    EventKind,
    PlanKind,
    SourceEvent,
)
from runtime.storage.db import create_schema, make_engine, make_session_factory
from runtime.storage.models import DeliveryAttempt, DeliveryJob
from runtime.storage.repos import (
    DeliveryJobRepository,
    EventInboxRepository,
    LeaseRepository,
    MappingRepository,
)


@pytest_asyncio.fixture()
async def session(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db")
    await create_schema(engine)
    factory = make_session_factory(engine)
    async with factory() as s:
        yield s
    await engine.dispose()


def _event(kind=EventKind.CREATE, msg=1, rev=1):
    raw = RawUpdate(kind=kind, chat_id=100, message_id=msg,
                    chat_class=ChatClass.BROADCAST,
                    edit_date_ts=rev if kind is EventKind.EDIT else None)
    return EventNormalizer().normalize(raw, "a1")


def _plan(kind=PlanKind.SEND, msg=1, rev=1, route="rt1", delay_s=0, grouped_id=None):
    return DeliveryPlan(
        kind=kind, rule_id="r1", rule_version=1, route_id=route, account_id="a1",
        source_scope="peer:100", source_chat_id=100, source_message_id=msg,
        revision=rev, target_chat_id=200, target_topic_id=None,
        mode=CloneMode.COPY, payload_ref="ref", payload_hash="h1",
        requires_approval=False, delay_s=delay_s, grouped_id=grouped_id,
    )


def _source_event(kind=EventKind.CREATE, msg=1, rev=1, grouped_id=None):
    return SourceEvent(
        kind=kind, source_scope="peer:100", source_chat_id=100,
        source_message_id=msg, revision=rev, account_id="a1",
        grouped_id=grouped_id,
    )


async def _drain_plans(session, entries):
    repo = EventInboxRepository(session)
    plans = {}
    for event, plan in entries:
        await repo.ingest(event, tenant_id="t", project_id="p")
        plans[(event.kind.value, event.source_message_id)] = plan
    rows = await repo.next_unprocessed()
    await repo.drain_to_jobs(
        rows,
        lambda row: [plans[(row.kind, row.source_message_id)]],
        tenant_id="t",
        project_id="p",
    )
    from sqlalchemy import select

    return (await session.execute(select(DeliveryJob))).scalars().all()


def test_inbox_dedup(session: AsyncSession):
    repo = EventInboxRepository(session)
    ev = _event()
    assert asyncio.run(repo.ingest(ev, tenant_id="t", project_id="p")) is True
    # second ingest of same kind+revision is a duplicate
    assert asyncio.run(repo.ingest(_event(), tenant_id="t", project_id="p")) is False
    # a new revision is a fresh event
    assert asyncio.run(repo.ingest(_event(kind=EventKind.EDIT, rev=99),
                                   tenant_id="t", project_id="p")) is True


def test_inbox_delete_sets_tombstone(session: AsyncSession):
    repo = EventInboxRepository(session)
    assert asyncio.run(repo.ingest(_event(), tenant_id="t", project_id="p"))
    assert asyncio.run(repo.ingest(_event(kind=EventKind.DELETE, rev=2**31 - 1),
                                   tenant_id="t", project_id="p"))
    from sqlalchemy import select
    from runtime.storage.models import SourceMessage
    row = asyncio.run(session.execute(select(SourceMessage))).scalar_one()
    assert row.tombstone is True


def test_job_create_dedup_by_idempotency(session: AsyncSession):
    repo = DeliveryJobRepository(session)
    p = _plan()
    assert asyncio.run(repo.create_from_plan(p, tenant_id="t", project_id="p"))
    assert asyncio.run(repo.create_from_plan(p, tenant_id="t", project_id="p")) is None


def test_approval_policy_sets_waiting(session: AsyncSession):
    repo = DeliveryJobRepository(session)
    p = _plan()
    p2 = DeliveryPlan(**{**p.__dict__, "requires_approval": True,
                         "route_id": "rt2"})
    job_id = asyncio.run(repo.create_from_plan(p2, tenant_id="t", project_id="p"))
    assert job_id
    # waiting_approval never gets claimed
    assert asyncio.run(repo.claim_next("a1", worker_generation=1)) is None


def test_claim_is_atomic_and_records_attempt(session: AsyncSession):
    repo = DeliveryJobRepository(session)
    asyncio.run(repo.create_from_plan(_plan(), tenant_id="t", project_id="p"))
    job = asyncio.run(repo.claim_next("a1", worker_generation=3))
    assert job is not None and job.status == "leased" and job.attempt_count == 1
    # second claim sees leased -> nothing ready
    assert asyncio.run(repo.claim_next("a1", worker_generation=3)) is None
    # transition back to ready (cancel lease), claim again -> attempt_no=2
    assert asyncio.run(repo.transition(job.id, "leased", "ready"))
    job2 = asyncio.run(repo.claim_next("a1", worker_generation=3))
    assert job2.attempt_count == 2


async def _make_stale_sending_job(session, kind):
    from sqlalchemy import update

    repo = DeliveryJobRepository(session)
    job_id = await repo.create_from_plan(
        _plan(kind=kind), tenant_id="t", project_id="p")
    assert job_id is not None
    job = await repo.claim_next("a1", worker_generation=1)
    assert job is not None and job.id == job_id
    assert await repo.transition(job.id, "leased", "sending")
    stale_at = datetime.now(timezone.utc) - timedelta(minutes=6)
    await session.execute(
        update(DeliveryJob)
        .where(DeliveryJob.id == job_id)
        .values(updated_at=stale_at)
    )
    await session.commit()
    return repo, job


async def test_stale_send_becomes_uncertain_and_is_not_reclaimed(session):
    from sqlalchemy import select

    repo, job = await _make_stale_sending_job(session, PlanKind.SEND)

    assert await repo.claim_next("a1", worker_generation=1) is None
    await session.refresh(job)
    assert job.status == "uncertain"
    assert job.last_error_class == "result_unknown"
    attempt = (await session.execute(
        select(DeliveryAttempt).where(DeliveryAttempt.job_id == job.id)
    )).scalar_one()
    assert attempt.result_status == "abandoned"
    assert attempt.error_class == "result_unknown"
    assert attempt.finished_at is not None


async def test_stale_edit_returns_ready_and_can_be_claimed_again(session):
    repo, job = await _make_stale_sending_job(session, PlanKind.EDIT)

    await repo._reclaim_stale_sending("a1")
    await session.refresh(job)
    assert job.status == "ready"

    claimed = await repo.claim_next("a1", worker_generation=1)
    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == "leased"


def test_claim_respects_next_attempt_and_flood(session: AsyncSession):
    repo = DeliveryJobRepository(session)
    p = _plan()
    job_id = asyncio.run(repo.create_from_plan(p, tenant_id="t", project_id="p"))
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert asyncio.run(repo.transition(job_id, "ready", "retry_wait"))
    assert asyncio.run(repo.transition(job_id, "retry_wait", "ready",
                                       next_attempt_at=future))
    assert asyncio.run(repo.claim_next("a1", worker_generation=1)) is None


async def test_claim_promotes_due_retry_wait_and_increments_attempt(session):
    repo = DeliveryJobRepository(session)
    job_id = await repo.create_from_plan(_plan(), tenant_id="t", project_id="p")
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await repo.transition(job_id, "ready", "retry_wait",
                                 next_attempt_at=past)

    job = await repo.claim_next("a1", worker_generation=1)

    assert job is not None
    assert job.status == "leased"
    assert job.attempt_count == 1


async def test_claim_does_not_promote_retry_wait_before_next_attempt(session):
    repo = DeliveryJobRepository(session)
    job_id = await repo.create_from_plan(_plan(), tenant_id="t", project_id="p")
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert await repo.transition(job_id, "ready", "retry_wait",
                                 next_attempt_at=future)

    assert await repo.claim_next("a1", worker_generation=1) is None
    job = await session.get(DeliveryJob, job_id)
    assert job is not None and job.status == "retry_wait"


async def test_claim_does_not_promote_retry_wait_during_flood_wait(session):
    repo = DeliveryJobRepository(session)
    job_id = await repo.create_from_plan(_plan(), tenant_id="t", project_id="p")
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert await repo.transition(job_id, "ready", "retry_wait",
                                 flood_wait_until=future)

    assert await repo.claim_next("a1", worker_generation=1) is None
    job = await session.get(DeliveryJob, job_id)
    assert job is not None and job.status == "retry_wait"


async def test_claim_only_promotes_retry_wait_for_requested_account(session):
    repo = DeliveryJobRepository(session)
    plan = _plan()
    other_account_plan = DeliveryPlan(**{**plan.__dict__, "account_id": "a2"})
    job_id = await repo.create_from_plan(
        other_account_plan, tenant_id="t", project_id="p")
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert await repo.transition(job_id, "ready", "retry_wait",
                                 next_attempt_at=past)

    assert await repo.claim_next("a1", worker_generation=1) is None
    job = await session.get(DeliveryJob, job_id)
    assert job is not None and job.status == "retry_wait"


async def test_drain_schedules_delayed_send_and_claim_skips_it(session: AsyncSession):
    jobs = await _drain_plans(
        session,
        [(_source_event(), _plan(delay_s=30))],
    )
    assert len(jobs) == 1
    assert jobs[0].next_attempt_at > datetime.now(timezone.utc)
    assert await DeliveryJobRepository(session).claim_next("a1", worker_generation=1) is None


async def test_drain_keeps_delayed_sends_in_route_order(session: AsyncSession):
    jobs = await _drain_plans(
        session,
        [
            (_source_event(msg=1), _plan(msg=1, delay_s=10)),
            (_source_event(msg=2), _plan(msg=2, delay_s=1)),
        ],
    )
    jobs.sort(key=lambda job: job.source_message_id)
    assert jobs[1].next_attempt_at >= jobs[0].next_attempt_at + timedelta(seconds=1)


async def test_album_members_reuse_first_due_time_in_same_batch(session: AsyncSession):
    jobs = await _drain_plans(
        session,
        [
            (
                _source_event(msg=1, grouped_id=77),
                _plan(msg=1, delay_s=10, grouped_id=77),
            ),
            (
                _source_event(msg=2, grouped_id=77),
                _plan(msg=2, delay_s=30, grouped_id=77),
            ),
        ],
    )
    assert len(jobs) == 2
    assert jobs[0].next_attempt_at == jobs[1].next_attempt_at


async def test_edit_is_skipped_while_copy_send_is_delayed(session: AsyncSession):
    jobs = await _drain_plans(
        session,
        [
            (_source_event(msg=1), _plan(msg=1, delay_s=30)),
            (
                _source_event(kind=EventKind.EDIT, msg=1, rev=2),
                _plan(kind=PlanKind.EDIT, msg=1, rev=2),
            ),
        ],
    )
    assert len(jobs) == 1
    assert jobs[0].kind == PlanKind.SEND.value


async def test_delete_cancels_pending_send_and_adds_delete_job(session: AsyncSession):
    jobs = await _drain_plans(
        session,
        [
            (_source_event(msg=1), _plan(msg=1, delay_s=30)),
            (
                _source_event(kind=EventKind.DELETE, msg=1, rev=2),
                _plan(kind=PlanKind.DELETE, msg=1, rev=2),
            ),
        ],
    )
    assert len(jobs) == 2
    send = next(job for job in jobs if job.kind == PlanKind.SEND.value)
    delete = next(job for job in jobs if job.kind == PlanKind.DELETE.value)
    assert send.status == "cancelled"
    assert send.last_error_class == "source_deleted"
    assert delete.status == "ready"


def test_mapping_record_and_reverse_lookup(session: AsyncSession):
    repo = MappingRepository(session)
    p = _plan(msg=42)
    rid = asyncio.run(repo.record(p, 9001, tenant_id="t", project_id="p", job_id=None))
    assert rid
    assert asyncio.run(repo.find_target_message_id("rt1", "peer:100", 100, 42)) == 9001
    assert asyncio.run(repo.find_target_message_id("rt1", "peer:100", 100, 43)) is None
    # duplicate (same route+source+part) is rejected, not duplicated
    assert asyncio.run(repo.record(p, 9002, tenant_id="t", project_id="p",
                                   job_id=None)) is None


def test_mapping_tombstone_not_hard_delete(session: AsyncSession):
    repo = MappingRepository(session)
    rid = asyncio.run(repo.record(_plan(), 9001, tenant_id="t", project_id="p",
                                  job_id=None))
    assert asyncio.run(repo.mark_deleted(rid))
    assert asyncio.run(repo.find_target_message_id("rt1", "peer:100", 100, 1)) is None


def test_lease_acquire_renew_takeover(session: AsyncSession):
    repo = LeaseRepository(session, ttl_s=0.05)
    gen = asyncio.run(repo.acquire("a1", "w1"))
    assert gen == 1
    # other worker cannot take a live lease
    assert asyncio.run(repo.acquire("a1", "w2")) is None
    # renew with right generation works, wrong doesn't
    assert asyncio.run(repo.renew("a1", "w1", gen)) is True
    assert asyncio.run(repo.renew("a1", "w1", 99)) is False
    # after expiry, takeover bumps generation
    import time
    time.sleep(0.06)
    gen2 = asyncio.run(repo.acquire("a1", "w2"))
    assert gen2 == 2
    # stale generation holder can no longer renew
    assert asyncio.run(repo.renew("a1", "w1", 1)) is False

"""Repositories implementing §6.4 transaction boundaries.

Each public method is one transaction's boundary; callers compose the five
boundary steps (inbox / plan / claim / result / approval) from these. The claim
path uses conditional UPDATE (lease CAS) — safe on both Postgres and sqlite;
Postgres deployments may additionally add FOR UPDATE SKIP LOCKED scanning.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from runtime.planner.model import DeliveryPlan, SourceEvent

from .models import (
    AccountLease,
    DeliveryAttempt,
    DeliveryJob,
    EventInbox,
    MessageMap,
    SourceMessage,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """sqlite drops tzinfo; normalize comparisons to aware UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class EventInboxRepository:
    """§6.4 boundary 1: one tx = source_message revision + dedup'd event row."""

    def __init__(self, session: AsyncSession):
        self.s = session

    async def ingest(self, event: SourceEvent, *, tenant_id: str, project_id: str,
                     ingest_seq: int = 0) -> bool:
        """Returns False when the event duplicates an existing inbox row."""
        stmt = select(SourceMessage).where(
            SourceMessage.tenant_id == tenant_id,
            SourceMessage.project_id == project_id,
            SourceMessage.source_scope == event.source_scope,
            SourceMessage.source_chat_id == event.source_chat_id,
            SourceMessage.source_message_id == event.source_message_id,
        )
        source = (await self.s.execute(stmt)).scalar_one_or_none()
        if source is None:
            source = SourceMessage(
                tenant_id=tenant_id, project_id=project_id,
                source_scope=event.source_scope, source_chat_id=event.source_chat_id,
                source_message_id=event.source_message_id,
                latest_revision=event.revision, grouped_id=event.grouped_id,
                content_hash=event.payload_hash,
            )
            self.s.add(source)
        else:
            if event.revision > source.latest_revision:
                source.latest_revision = event.revision
                if event.payload_hash:
                    source.content_hash = event.payload_hash
            if event.kind.value == "delete":
                source.tombstone = True

        self.s.add(EventInbox(
            event_id=f"{event.source_scope}:{event.source_chat_id}:"
                     f"{event.source_message_id}:{event.kind.value}:{event.revision}",
            source_scope=event.source_scope, source_chat_id=event.source_chat_id,
            source_message_id=event.source_message_id, kind=event.kind.value,
            revision=event.revision, account_id=event.account_id,
            payload_ref=event.payload_ref, payload_hash=event.payload_hash,
            grouped_id=event.grouped_id, topic_id=event.topic_id,
            reply_to_source_id=event.reply_to_source_id,
            protected=event.protected, source_sender_id=event.sender_id,
            ingest_seq=ingest_seq,
        ))
        try:
            await self.s.commit()
        except IntegrityError:
            await self.s.rollback()
            return False
        return True


    async def next_unprocessed(self, *, limit: int = 200) -> list[EventInbox]:
        rows = (await self.s.execute(
            select(EventInbox)
            .where(EventInbox.processed.is_(False))
            .order_by(EventInbox.ingest_seq).limit(limit)
        )).scalars().all()
        return list(rows)

    async def drain_to_jobs(self, rows: list[EventInbox], plans_for, *,
                            tenant_id: str, project_id: str) -> int:
        """§6.4 boundary 2 (plan side): for each unprocessed inbox row, build
        DeliveryPlans via plans_for(row) and insert jobs; mark the row
        processed. One commit for the whole batch; per-plan savepoint turns
        an idempotency-key conflict into a skip instead of a batch abort."""
        for row in rows:
            for plan in plans_for(row):
                job = _job_from_plan(plan, tenant_id=tenant_id,
                                     project_id=project_id)
                try:
                    async with self.s.begin_nested():
                        self.s.add(job)
                        await self.s.flush()
                except IntegrityError:
                    self.s.expunge(job)
            row.processed = True
        await self.s.commit()
        return len(rows)


class DeliveryJobRepository:
    """§6.4 boundary 2/3: plan creation (idempotent) + conditional claim."""

    def __init__(self, session: AsyncSession):
        self.s = session

    async def create_from_plan(self, plan: DeliveryPlan, *,
                               tenant_id: str, project_id: str) -> str | None:
        """Returns job id, or None when the idempotency key already exists."""
        job = _job_from_plan(plan, tenant_id=tenant_id, project_id=project_id)
        self.s.add(job)
        try:
            await self.s.commit()
        except IntegrityError:
            await self.s.rollback()
            return None
        return job.id

    async def record_result(self, job: DeliveryJob, *, attempt_no: int,
                            new_status: str, error_class: str | None = None,
                            next_attempt_at: datetime | None = None,
                            flood_wait_until: datetime | None = None,
                            target_message_id: int | None = None,
                            request_ref: str | None = None) -> bool:
        """§6.4 boundary 4: finish the attempt row, move the job, and (on a
        successful SEND) write message_map — one commit. Returns False when the
        job no longer sits in 'sending' (e.g. superseded by a newer revision)."""
        now = _utcnow()
        res = await self.s.execute(
            update(DeliveryJob)
            .where(DeliveryJob.id == job.id, DeliveryJob.status == "sending")
            .values(status=new_status, next_attempt_at=next_attempt_at,
                    flood_wait_until=flood_wait_until, last_error_class=error_class)
        )
        if res.rowcount == 0:
            await self.s.rollback()
            return False
        await self.s.execute(
            update(DeliveryAttempt)
            .where(DeliveryAttempt.job_id == job.id,
                   DeliveryAttempt.attempt_no == attempt_no)
            .values(finished_at=now, result_status=new_status,
                    error_class=error_class, request_ref=request_ref)
        )
        if new_status == "succeeded" and job.kind == "send" \
                and target_message_id is not None:
            row = MessageMap(
                tenant_id=job.tenant_id, project_id=job.project_id,
                rule_id=job.rule_id, route_id=job.route_id,
                rule_version_at_create=job.rule_version,
                source_scope=job.source_scope, source_chat_id=job.source_chat_id,
                source_message_id=job.source_message_id,
                source_album_id=job.grouped_id,
                sender_account_id=job.account_id, target_chat_id=job.target_chat_id,
                target_topic_id=job.target_topic_id,
                target_message_id=target_message_id,
                last_applied_revision=job.revision, delivery_job_id=job.id,
            )
            try:
                async with self.s.begin_nested():
                    self.s.add(row)
                    await self.s.flush()
            except IntegrityError:
                self.s.expunge(row)  # map already written by a twin attempt
        await self.s.commit()
        return True

    async def claim_next(self, account_id: str, *, worker_generation: int) -> DeliveryJob | None:
        """Atomic conditional update: first due ready job for the account goes
        READY -> LEASED and records the attempt row (same tx, §6.4 boundary 3)."""
        now = _utcnow()
        stmt = (
            select(DeliveryJob)
            .where(DeliveryJob.account_id == account_id,
                   DeliveryJob.status == "ready")
            .order_by(DeliveryJob.created_at)
        )
        candidates = (await self.s.execute(stmt)).scalars().all()
        for job in candidates:
            due = _aware(job.next_attempt_at)
            flood = _aware(job.flood_wait_until)
            if due is not None and due > now:
                continue
            if flood is not None and flood > now:
                continue
            next_attempt = job.attempt_count + 1
            res = await self.s.execute(
                update(DeliveryJob)
                .where(DeliveryJob.id == job.id, DeliveryJob.status == "ready")
                .values(status="leased", attempt_count=next_attempt)
            )
            if res.rowcount == 0:
                continue  # lost the race; try next candidate
            self.s.add(DeliveryAttempt(job_id=job.id,
                                       attempt_no=next_attempt,
                                       worker_generation=worker_generation,
                                       started_at=now))
            await self.s.commit()
            await self.s.refresh(job)
            return job
        return None

    async def transition(self, job_id: str, src: str, dst: str, *,
                         next_attempt_at: datetime | None = None,
                         flood_wait_until: datetime | None = None,
                         error_class: str | None = None) -> bool:
        """Guarded status update honoring the §8.2 edge set (validated by the
        caller via delivery.model.transition)."""
        res = await self.s.execute(
            update(DeliveryJob)
            .where(DeliveryJob.id == job_id, DeliveryJob.status == src)
            .values(status=dst, next_attempt_at=next_attempt_at,
                    flood_wait_until=flood_wait_until, last_error_class=error_class)
        )
        await self.s.commit()
        return res.rowcount == 1


class MappingRepository:
    """§6.3 message_map writes + reverse lookups for replies/loop guard."""

    def __init__(self, session: AsyncSession):
        self.s = session

    async def record(self, plan: DeliveryPlan, target_message_id: int, *,
                     tenant_id: str, project_id: str, job_id: str | None,
                     output_part_index: int = 0,
                     member_index: int | None = None) -> str | None:
        row = MessageMap(
            tenant_id=tenant_id, project_id=project_id, rule_id=plan.rule_id,
            route_id=plan.route_id, rule_version_at_create=plan.rule_version,
            source_scope=plan.source_scope, source_chat_id=plan.source_chat_id,
            source_message_id=plan.source_message_id,
            source_album_id=plan.grouped_id, source_member_index=member_index,
            sender_account_id=plan.account_id, target_chat_id=plan.target_chat_id,
            target_topic_id=plan.target_topic_id,
            target_message_id=target_message_id,
            output_part_index=output_part_index,
            last_applied_revision=plan.revision, delivery_job_id=job_id,
        )
        self.s.add(row)
        try:
            await self.s.commit()
        except IntegrityError:
            await self.s.rollback()
            return None
        return row.id

    async def lookup_many(self, source_scope: str, source_chat_id: int,
                          source_message_ids) -> list[MessageMap]:
        """Batch reverse-lookup source for reply resolution prefetch."""
        if not source_message_ids:
            return []
        rows = (await self.s.execute(
            select(MessageMap).where(
                MessageMap.source_scope == source_scope,
                MessageMap.source_chat_id == source_chat_id,
                MessageMap.source_message_id.in_(list(source_message_ids)),
                MessageMap.deleted_at.is_(None),
            ))).scalars().all()
        return list(rows)

    async def find_target_message_id(self, route_id: str, source_scope: str,
                                     source_chat_id: int,
                                     source_message_id: int) -> int | None:
        stmt = select(MessageMap.target_message_id).where(
            MessageMap.route_id == route_id,
            MessageMap.source_scope == source_scope,
            MessageMap.source_chat_id == source_chat_id,
            MessageMap.source_message_id == source_message_id,
            MessageMap.deleted_at.is_(None),
            MessageMap.output_part_index == 0,
        )
        return (await self.s.execute(stmt)).scalar_one_or_none()

    async def mark_deleted(self, map_id: str) -> bool:
        """Tombstone, never hard delete (§6.3: mapping survives failures)."""
        res = await self.s.execute(
            update(MessageMap)
            .where(MessageMap.id == map_id)
            .values(deleted_at=_utcnow(), status="deleted")
        )
        await self.s.commit()
        return res.rowcount == 1


class LeaseRepository:
    """§5.3 CAS ownership: acquire returns the new generation, renew extends
    the same generation — mismatching generation always loses."""

    def __init__(self, session: AsyncSession, *, ttl_s: float = 45.0):
        self.s = session
        self.ttl_s = ttl_s

    async def acquire(self, account_id: str, worker_id: str) -> int | None:
        """Take the lease if free or expired; bumps generation. Returns the
        generation held, or None when someone else holds a live lease."""
        now = _utcnow()
        until = now + timedelta(seconds=self.ttl_s)
        row = (await self.s.execute(
            select(AccountLease).where(AccountLease.account_id == account_id)
        )).scalar_one_or_none()
        if row is None:
            self.s.add(AccountLease(account_id=account_id, worker_id=worker_id,
                                    generation=1, lease_until=until))
            try:
                await self.s.commit()
            except IntegrityError:
                await self.s.rollback()
                return None
            return 1
        if row.worker_id == worker_id:
            res = await self.s.execute(
                update(AccountLease)
                .where(AccountLease.account_id == account_id,
                       AccountLease.worker_id == worker_id)
                .values(lease_until=until)
            )
            await self.s.commit()
            return row.generation if res.rowcount == 1 else None
        if _aware(row.lease_until) > now:
            return None  # someone else holds a live lease
        new_generation = row.generation + 1
        res = await self.s.execute(
            update(AccountLease)
            .where(AccountLease.account_id == account_id,
                   AccountLease.generation == row.generation,
                   AccountLease.lease_until <= now)
            .values(worker_id=worker_id, generation=new_generation,
                    lease_until=until)
        )
        await self.s.commit()
        return new_generation if res.rowcount == 1 else None

    async def renew(self, account_id: str, worker_id: str, generation: int) -> bool:
        until = _utcnow() + timedelta(seconds=self.ttl_s)
        res = await self.s.execute(
            update(AccountLease)
            .where(AccountLease.account_id == account_id,
                   AccountLease.worker_id == worker_id,
                   AccountLease.generation == generation)
            .values(lease_until=until)
        )
        await self.s.commit()
        return res.rowcount == 1


def _job_from_plan(plan: DeliveryPlan, *, tenant_id: str,
                   project_id: str) -> DeliveryJob:
    return DeliveryJob(
        tenant_id=tenant_id, project_id=project_id,
        idempotency_key=plan.idempotency_key, kind=plan.kind.value,
        route_id=plan.route_id, rule_id=plan.rule_id,
        rule_version=plan.rule_version, account_id=plan.account_id,
        source_scope=plan.source_scope, source_chat_id=plan.source_chat_id,
        source_message_id=plan.source_message_id, revision=plan.revision,
        target_chat_id=plan.target_chat_id, target_topic_id=plan.target_topic_id,
        mode=plan.mode.value, payload_ref=plan.payload_ref,
        payload_hash=plan.payload_hash, requires_approval=plan.requires_approval,
        reply_to_target_message_id=plan.reply_to_target_message_id,
        grouped_id=plan.grouped_id,
        status="waiting_approval" if plan.requires_approval else "ready",
    )

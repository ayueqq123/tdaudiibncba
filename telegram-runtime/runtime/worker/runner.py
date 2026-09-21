"""Worker host: one worker process hosts many accounts, each isolated by its
own lease + runner (§1.1 multi-tenant worker, §5.3).

AccountRunner.run_once composes the §6.4 boundaries:
  inbox drain (tx1→tx2) -> claim (tx3) -> policy gate -> execute -> record (tx4).

Every Telegram side effect still funnels through DeliveryExecutor -> SendPolicy;
the runner never sends directly. Auth-dead / storage-down errors halt the
account runner instead of looping retries (§8.3).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from runtime.delivery.executor import DeliveryExecutor, ResultStatus
from runtime.delivery.model import (
    ErrorClass,
    JobStatus,
    RetryPolicy,
    classify_error,
    next_attempt_at,
)
from runtime.delivery.policy import (
    ApprovalRecord,
    Decision,
    LiveAccount,
    PolicyCheckable,
    PolicySnapshot,
    check,
)
from runtime.planner.model import (
    CloneMode,
    DeliveryPlan,
    EventKind,
    PlanKind,
    RuleSnapshot,
    SourceEvent,
)
from runtime.planner.planner import ClonePlanner, MappingView
from runtime.storage.models import DeliveryJob, EventInbox, MessageMap
from runtime.storage.repos import (
    DeliveryJobRepository,
    EventInboxRepository,
    MappingRepository,
)

_JOB_KIND_ALIAS = {
    "send": PlanKind.SEND,
    "send_message": PlanKind.SEND,   # platform writes 'send_message' (§10.1 chain)
    "edit": PlanKind.EDIT,
    "delete": PlanKind.DELETE,
    "tombstone": PlanKind.TOMBSTONE,
}


def plan_from_job(job: DeliveryJob) -> DeliveryPlan:
    kind = _JOB_KIND_ALIAS.get(job.kind)
    if kind is None:
        raise ValueError(f"unknown delivery job kind: {job.kind}")
    return DeliveryPlan(
        kind=kind, rule_id=job.rule_id,
        rule_version=job.rule_version, route_id=job.route_id,
        account_id=job.account_id, source_scope=job.source_scope,
        source_chat_id=job.source_chat_id,
        source_message_id=job.source_message_id, revision=job.revision,
        target_chat_id=job.target_chat_id, target_topic_id=job.target_topic_id,
        mode=CloneMode(job.mode), payload_ref=job.payload_ref,
        payload_hash=job.payload_hash, requires_approval=job.requires_approval,
        reply_to_target_message_id=job.reply_to_target_message_id,
        grouped_id=job.grouped_id,
    )


def event_from_inbox(row: EventInbox) -> SourceEvent:
    return SourceEvent(
        kind=EventKind(row.kind), source_scope=row.source_scope,
        source_chat_id=row.source_chat_id,
        source_message_id=row.source_message_id, revision=row.revision,
        account_id=row.account_id, grouped_id=row.grouped_id,
        payload_ref=row.payload_ref, payload_hash=row.payload_hash,
        reply_to_source_id=row.reply_to_source_id, topic_id=row.topic_id,
        protected=row.protected,
    )


RulesProvider = Callable[[str], list[RuleSnapshot]]
LiveProvider = Callable[[str], LiveAccount]
PolicyProvider = Callable[[], PolicySnapshot]
ApprovalProvider = Callable[[DeliveryJob], ApprovalRecord | None]


class _DictMappingView(MappingView):
    """Sync MappingView prefetched for a drain batch — planner stays sync."""

    def __init__(self, rows: list[MessageMap]):
        self._m = {(r.route_id, r.source_scope, r.source_chat_id,
                    r.source_message_id): r.target_message_id for r in rows}

    def find_target_message_id(self, route_id: str, source_scope: str,
                               source_chat_id: int,
                               source_message_id: int) -> int | None:
        return self._m.get((route_id, source_scope, source_chat_id,
                            source_message_id))


@dataclass
class RunnerDeps:
    session_factory: async_sessionmaker[AsyncSession]
    executor: DeliveryExecutor
    rules: RulesProvider
    live: LiveProvider
    policy: PolicyProvider
    approvals: ApprovalProvider = lambda _job: None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    clock: Callable[[], float] = time.time
    tenant_id: str = ""
    project_id: str = ""


class AccountRunner:
    """Per-account loop. `halted` set on auth_dead/storage_down/lease loss —
    the host must stop it and surface the state (§8.3)."""

    def __init__(self, account_id: str, generation: int, deps: RunnerDeps):
        self.account_id = account_id
        self.generation = generation
        self.deps = deps
        self.halted: str | None = None

    async def drain_inbox(self, *, limit: int = 200) -> int:
        d = self.deps
        async with d.session_factory() as s:
            inbox = EventInboxRepository(s)
            rows = await inbox.next_unprocessed(limit=limit)
            if not rows:
                return 0
            # prefetch message_map for reply resolution (planner is sync)
            maps: list[MessageMap] = []
            mapping_repo = MappingRepository(s)
            by_scope: dict[tuple[str, int], set[int]] = {}
            for row in rows:
                ids = by_scope.setdefault(
                    (row.source_scope, row.source_chat_id), set())
                ids.add(row.source_message_id)
                if row.reply_to_source_id is not None:
                    ids.add(row.reply_to_source_id)
            for (scope, chat), ids in by_scope.items():
                maps.extend(await mapping_repo.lookup_many(scope, chat, ids))
            planner = ClonePlanner(_DictMappingView(maps))

            def plans_for(row: EventInbox):
                return planner.plan(event_from_inbox(row),
                                    d.rules(row.account_id))

            return await inbox.drain_to_jobs(
                rows, plans_for, tenant_id=d.tenant_id, project_id=d.project_id)

    async def send_next(self) -> str | None:
        """Claim → gate → execute → record. Returns the job id acted on."""
        d = self.deps
        async with d.session_factory() as s:
            jobs = DeliveryJobRepository(s)
            job = await jobs.claim_next(self.account_id,
                                        worker_generation=self.generation)
            if job is None:
                return None
            attempt_no = job.attempt_count
            plan = plan_from_job(job)

            live = d.live(self.account_id)
            decision = check(
                PolicyCheckable(
                    account_id=plan.account_id, rule_id=plan.rule_id,
                    route_id=plan.route_id, tenant_id=job.tenant_id,
                    project_id=job.project_id,
                    expected_generation=self.generation,
                    requires_approval=plan.requires_approval,
                    content_hash=plan.payload_hash),
                live, d.policy(), d.approvals(job), now=d.clock())

            if decision is Decision.BLOCKED_LEASE:
                self.halted = "lease_lost"
                await jobs.transition(job.id, "leased", "ready")
                return job.id
            if decision is Decision.BLOCKED_RATE:
                await jobs.transition(
                    job.id, "leased", "ready",
                    next_attempt_at=_dt(next_attempt_at(
                        d.retry_policy, attempt_no, now=d.clock())))
                return job.id
            if decision is not Decision.ALLOW:
                await jobs.transition(job.id, "leased", "blocked")
                return job.id

            await jobs.transition(job.id, "leased", "sending")

            result = await d.executor.execute(
                plan, live=live, policy=d.policy(), approval=d.approvals(job),
                expected_generation=self.generation,
                tenant_id=job.tenant_id, project_id=job.project_id,
                now=d.clock())

            await self._record(jobs, job, attempt_no, result)
            return job.id

    async def _record(self, jobs: DeliveryJobRepository, job: DeliveryJob,
                      attempt_no: int, result) -> None:
        """Map executor outcome -> §8.2 status + §8.3 error action, one tx."""
        if result.status is ResultStatus.SUCCEEDED:
            await jobs.record_result(
                job, attempt_no=attempt_no, new_status=JobStatus.SUCCEEDED.value,
                target_message_id=(result.target_message_ids[0]
                                   if result.target_message_ids else None))
            return
        if result.status is ResultStatus.POLICY_DENIED:
            await jobs.record_result(job, attempt_no=attempt_no,
                                     new_status=JobStatus.BLOCKED.value)
            return
        if result.status is ResultStatus.BLOCKED:
            await jobs.record_result(
                job, attempt_no=attempt_no, new_status=JobStatus.BLOCKED.value,
                error_class=(result.error_class.value
                             if result.error_class else None))
            return
        if result.status is ResultStatus.UNCERTAIN:
            await jobs.record_result(
                job, attempt_no=attempt_no, new_status=JobStatus.UNCERTAIN.value,
                error_class=ErrorClass.RESULT_UNKNOWN.value)
            return
        if result.status is ResultStatus.RETRYABLE:
            action = classify_error(result.error_class,
                                    flood_wait_until=result.flood_wait_until)
            if action.flood_wait_until is not None:
                await jobs.record_result(
                    job, attempt_no=attempt_no,
                    new_status=JobStatus.RETRY_WAIT.value,
                    error_class=result.error_class.value,
                    flood_wait_until=_dt(action.flood_wait_until))
                return
            nxt = next_attempt_at(self.deps.retry_policy, attempt_no,
                                  now=self.deps.clock())
            if nxt is None:
                await jobs.record_result(
                    job, attempt_no=attempt_no,
                    new_status=JobStatus.DEAD_LETTER.value,
                    error_class=result.error_class.value)
            else:
                await jobs.record_result(
                    job, attempt_no=attempt_no,
                    new_status=JobStatus.RETRY_WAIT.value,
                    error_class=result.error_class.value,
                    next_attempt_at=_dt(nxt))
            return
        # FAILED: auth/content/permanent — §8.3 worker-level halts propagate up
        err = result.error_class
        if err in (ErrorClass.AUTH_DEAD, ErrorClass.STORAGE_DOWN,
                   ErrorClass.CACHE_DOWN):
            self.halted = err.value
        await jobs.record_result(
            job, attempt_no=attempt_no,
            new_status=JobStatus.FAILED_PERMANENT.value,
            error_class=err.value if err else None)

    async def run_once(self, *, limit: int = 200) -> None:
        """One poll round: drain inbox into jobs, then send while work is due."""
        if self.halted:
            return
        await self.drain_inbox(limit=limit)
        while not self.halted:
            if await self.send_next() is None:
                break


class WorkerHost:
    """Hosts AccountRunners keyed by lease ownership. assign() is the only
    entry point — it must win the lease before any work starts (§5.3)."""

    def __init__(self, worker_id: str, deps: RunnerDeps):
        self.worker_id = worker_id
        self.deps = deps
        self.runners: dict[str, AccountRunner] = {}

    async def assign(self, account_id: str, generation: int) -> AccountRunner:
        """Call only after LeaseRepository.acquire succeeded for this worker —
        generation is the lease generation won."""
        runner = AccountRunner(account_id, generation, self.deps)
        self.runners[account_id] = runner
        return runner

    def release(self, account_id: str) -> None:
        self.runners.pop(account_id, None)

    async def run_once(self) -> None:
        """One round across accounts; a halted runner is isolated — its peers
        keep going (per-account blast radius, §1.1)."""
        await asyncio.gather(
            *(r.run_once() for r in list(self.runners.values())),
            return_exceptions=True,
        )


def _dt(ts: float | None) -> datetime | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc)

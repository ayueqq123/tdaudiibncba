"""WorkerHostMain: the production worker loop (§5.2/§5.3/§12).

Each poll round: reconcile platform assignments -> per-account leases ->
Telethon sessions -> AccountRunner ticks; then pull & apply runtime commands;
then one send/drain round per hosted runner. Per-account failure isolation:
a dead session or lost lease drops only that account's runner (§1.1).

Ownership order is deliberate: lease acquire happens BEFORE the Telegram
client connects, so a worker that lost its lease never performs sends
(§5.3 fencing)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from runtime.account.lease_heartbeat import LeaseHeartbeat
from runtime.delivery.executor import DeliveryExecutor
from runtime.delivery.model import RetryPolicy
from runtime.delivery.policy import ApprovalRecord, PolicySnapshot
from runtime.planner.model import (
    ApprovalPolicy,
    CloneMode,
    RouteTarget,
    RuleSnapshot,
)
from runtime.storage.repos import DeliveryJobRepository, LeaseRepository
from runtime.worker.control_client import (
    Assignment,
    ControlApiError,
    ControlClient,
    PendingCommand,
    SessionBundle,
)
from runtime.worker.live import (
    AccountSession,
    LiveRegistry,
    PayloadResolver,
    TelethonTransport,
    TransportRouter,
    make_ingest_handler,
    register_live_events,
)
from runtime.worker.runner import RunnerDeps, WorkerHost

log = logging.getLogger(__name__)

LEASE_TTL_S = 45.0
HEARTBEAT_S = 10.0


class SessionConnector(Protocol):
    async def __call__(self, bundle: SessionBundle) -> AccountSession: ...


def rules_from_snapshot(row: dict[str, Any], account_uuid: str) -> list[RuleSnapshot]:
    """Platform snapshot row -> runtime RuleSnapshots.

    Shape gap: the platform models one rule = N source→target targets
    (source_chat_id lives on each target), while runtime RuleSnapshot is one
    source + N routes. Each target expands into its own snapshot, and each
    source emits both scope spellings — canonical `peer:{cid}` for channels/
    supergroups and `peer:{cid}:acct:{uuid}` for small groups (§6.2) — so the
    planner's exact-match on event.source_scope works whichever class the
    peer turns out to be."""
    snap = row.get("snapshot") or {}
    rule = snap.get("rule") or {}
    version = int(row.get("version") or 0)
    rule_id = str(rule.get("id") or row.get("rule_id"))
    mode = CloneMode(rule.get("mode") or "copy")
    approval = (ApprovalPolicy.MESSAGE_REVIEW
                if rule.get("approval_policy") == "message_review"
                else ApprovalPolicy.RULE_AUTHORIZED)
    out: list[RuleSnapshot] = []
    for t in snap.get("targets") or []:
        route = RouteTarget(
            route_id=str(t["route_id"]),
            target_chat_id=int(t["target_chat_id"]),
            target_topic_id=t.get("target_topic_id"),
        )
        src_chat = int(t["source_chat_id"])
        for scope in (f"peer:{src_chat}", f"peer:{src_chat}:acct:{account_uuid}"):
            out.append(RuleSnapshot(
                rule_id=rule_id, version=version, account_id=account_uuid,
                source_scope=scope, source_chat_id=src_chat,
                source_topic_id=t.get("source_topic_id"),
                targets=(route,), mode=mode,
                sync_edit=bool(rule.get("sync_edit", True)),
                sync_delete=bool(rule.get("sync_delete", True)),
                approval_policy=approval,
                filters=(t.get("filters") or {},),
            ))
    return out


@dataclass
class _Hosted:
    assignment: Assignment
    session: AccountSession
    heartbeat: LeaseHeartbeat
    heartbeat_task: asyncio.Task


class WorkerHostMain:
    """Reconcile-driven host. `tick()` is one complete poll round — tests
    drive it directly; `run()` loops it under a stop event."""

    def __init__(
        self,
        worker_id: str,
        session_factory: async_sessionmaker[AsyncSession],
        control: ControlClient,
        *,
        session_connector: SessionConnector = AccountSession.connect,
        lease_ttl_s: float = LEASE_TTL_S,
        heartbeat_s: float = HEARTBEAT_S,
        policy: PolicySnapshot | None = None,
        retry_policy: RetryPolicy | None = None,
    ):
        self.worker_id = worker_id
        self.control = control
        self._session_factory = session_factory
        self._session_connector = session_connector
        self._lease_ttl = lease_ttl_s
        self._heartbeat_s = heartbeat_s

        self.registry = LiveRegistry()
        self.router = TransportRouter()
        self.resolver = PayloadResolver(control)
        self._rules_cache: dict[str, list[RuleSnapshot]] = {}
        self._hosted: dict[str, _Hosted] = {}
        self._lost: set[str] = set()
        self._seen_cmds: set[int] = set()
        self._policy = policy or PolicySnapshot()
        self._stopping = asyncio.Event()

        deps = RunnerDeps(
            session_factory=session_factory,
            executor=DeliveryExecutor(self.router),
            rules=lambda account_id: self._rules_cache.get(account_id, []),
            live=self.registry.get,
            policy=lambda: self._policy,
            approvals=self._approval_for,
            retry_policy=retry_policy or RetryPolicy(),
        )
        self._runner_host = WorkerHost(worker_id, deps)

    # ---------- lease + assignment lifecycle ----------

    async def reconcile(self) -> None:
        """Diff desired accounts vs hosted; assign new, release removed."""
        # 控制面不可用 ≠ 期望清空:keep hosting what we have (§8.3 降级而非拆除)
        try:
            assignments = await self.control.list_accounts()
        except Exception as exc:  # noqa: BLE001 — degraded tick, not a crash
            log.warning("control pull failed: %s", exc)
            assignments = None
        if assignments is not None:
            desired = {a.account_id: a for a in assignments}
            for account_id in set(self._hosted) - set(desired):
                await self._release(account_id, reason="unassigned")
            for account_id, assignment in desired.items():
                if account_id not in self._hosted:
                    await self._assign(assignment)

        for account_id in self._lost & set(self._hosted):
            await self._release(account_id, reason="lease_lost")
        self._lost.clear()

    async def _assign(self, a: Assignment) -> None:
        if not a.has_session:
            log.warning("account %s has no session material; skipping",
                        a.account_id)
            return
        async with self._session_factory() as s:
            generation = await LeaseRepository(
                s, ttl_s=self._lease_ttl).acquire(a.account_id, self.worker_id)
        if generation is None:
            log.info("lease held elsewhere account=%s", a.account_id)
            return
        try:
            bundle = await self.control.fetch_session(a.account_id)
            session = await self._session_connector(bundle)
        except Exception as exc:  # noqa: BLE001 — connect failure must not take the host down
            log.error("connect failed account=%s: %s", a.account_id, exc)
            await self._report_status(a.api_row_id, "error", str(exc))
            return
        try:
            register_live_events(
                session,
                make_ingest_handler(self._session_factory, a.account_id,
                                    a.tenant_id, a.project_id,
                                    control=self.control, api_row_id=a.api_row_id),
            )
            self.registry.register(a.account_id, generation)
            self.router.add(
                a.account_id,
                TelethonTransport(session.client, a.account_id,
                                  self.registry, self.resolver))
            await self._refresh_rules(a)
            await self._runner_host.assign(a.account_id, generation)
            hb = LeaseHeartbeat(
                self._make_renew(a.account_id, generation),
                interval_s=self._heartbeat_s,
                on_lost=lambda _r, aid=a.account_id: self._lost.add(aid))
            self._hosted[a.account_id] = _Hosted(
                assignment=a, session=session, heartbeat=hb,
                heartbeat_task=asyncio.create_task(hb.run()))
            await self._report_status(a.api_row_id, "active")
            log.info("assigned account=%s generation=%d", a.account_id,
                     generation)
        except Exception:
            await session.close()
            raise

    async def _report_status(self, api_row_id: int, status: str,
                             error: str = "") -> None:
        """Best-effort observed-status report to control-api (§5.3)."""
        try:
            await self.control.report_status(api_row_id, status, error)
        except Exception as exc:  # noqa: BLE001 — status report must never break the loop
            log.warning("status report failed account=%s: %s", api_row_id, exc)

    def _make_renew(self, account_id: str, generation: int):
        async def renew() -> bool:
            async with self._session_factory() as s:
                return await LeaseRepository(
                    s, ttl_s=self._lease_ttl).renew(
                        account_id, self.worker_id, generation)
        return renew

    async def _release(self, account_id: str, *, reason: str) -> None:
        hosted = self._hosted.pop(account_id, None)
        self._runner_host.release(account_id)
        self.router.drop(account_id)
        self.registry.drop(account_id)
        self._rules_cache.pop(account_id, None)
        if hosted is None:
            return
        hosted.heartbeat.stop()
        hosted.heartbeat_task.cancel()
        try:
            await hosted.session.close()
        except Exception:  # noqa: BLE001 — best-effort cleanup on release
            log.warning("session close failed account=%s", account_id)
        log.info("released account=%s reason=%s", account_id, reason)
        if reason != "lease_lost":
            await self._report_status(hosted.assignment.api_row_id, "stopped")
        # lease row left to expire by TTL — no release mutation (§5.3)

    # ---------- rules / commands ----------

    async def _refresh_rules(self, a: Assignment) -> None:
        try:
            rows = await self.control.pull_rules(a.api_row_id)
        except ControlApiError as exc:
            log.warning("rules pull failed account=%s: %s", a.account_id, exc)
            return
        snaps: list[RuleSnapshot] = []
        for r in rows:
            account_uuid = r.get("account_uuid") or a.account_id
            snaps.extend(rules_from_snapshot(r, account_uuid))
        self._rules_cache[a.account_id] = snaps

    async def poll_commands(self) -> None:
        for account_id, hosted in list(self._hosted.items()):
            try:
                cmds = await self.control.pull_commands(
                    hosted.assignment.api_row_id)
            except ControlApiError as exc:
                log.warning("commands pull failed account=%s: %s",
                            account_id, exc)
                continue
            for cmd in cmds:
                if cmd.id in self._seen_cmds:
                    continue
                self._seen_cmds.add(cmd.id)
                status, result = await self._apply_command(
                    account_id, hosted, cmd)
                try:
                    await self.control.ack_command(cmd.id, status, result)
                except ControlApiError as exc:
                    log.warning("ack failed command=%d: %s", cmd.id, exc)

    async def _apply_command(
        self, account_id: str, hosted: _Hosted, cmd: PendingCommand,
    ) -> tuple[str, str]:
        t = cmd.type
        try:
            if t == "StopAccount":
                await self._release(account_id, reason="command_stop")
                return "done", "released"
            if t == "StartAccount":
                return "done", "already_hosted"
            if t == "PauseAccount":
                self.registry.mark_paused(account_id)
                return "done", "paused"
            if t == "ResumeAccount":
                self.registry.mark_resumed(account_id)
                return "done", "resumed"
            if t == "ReloadConfig":
                await self._refresh_rules(hosted.assignment)
                return "done", "rules_refreshed"
            if t == "SyncChats":
                await hosted.session.client.get_dialogs()
                return "done", "dialogs_warmed"
            if t == "CancelJob":
                job_id = str((cmd.payload or {}).get("job_id") or "")
                ok = await self._cancel_job(job_id) if job_id else False
                return ("done", "cancelled") if ok else (
                    "rejected", "job_not_cancellable")
            # ReconcileSource 等未实现类型:显式拒收而不是沉默吞掉
            return "rejected", f"unsupported:{t}"
        except Exception as exc:
            log.exception("command %d failed", cmd.id)
            return "rejected", f"error:{type(exc).__name__}"

    async def _cancel_job(self, job_id: str) -> bool:
        async with self._session_factory() as s:
            jobs = DeliveryJobRepository(s)
            for src in ("ready", "retry_wait", "leased"):
                if await jobs.transition(job_id, src, "cancelled"):
                    return True
        return False

    @staticmethod
    def _approval_for(job) -> ApprovalRecord | None:
        """A delivery_job with requires_approval exists only because an
        approval row already bound its content hash (§10.1) — the job row
        itself is the proof; no second lookup needed."""
        if not job.requires_approval:
            return None
        return ApprovalRecord(approved=True, content_hash=job.payload_hash,
                              expires_at=None)

    # ---------- main loop ----------

    async def tick(self) -> None:
        await self.reconcile()
        await self.poll_commands()
        await self._runner_host.run_once()
        for account_id, runner in list(self._runner_host.runners.items()):
            if runner.halted:
                self._lost.add(account_id)

    async def run(self, poll_s: float = 2.0) -> None:
        while not self._stopping.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("worker tick failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=poll_s)
            except asyncio.TimeoutError:
                pass
        for account_id in list(self._hosted):
            await self._release(account_id, reason="shutdown")

    def stop(self) -> None:
        self._stopping.set()

"""Control-plane client: the worker's only channel to the platform (§12).

Authenticates with the shared service credential (X-Worker-Token) against
/api/v1/tg/runtime — the worker never holds a user JWT. All payloads come
back through FBA's response envelope ({code, msg, data}); this client
unwraps `data` and raises ControlApiError on non-success codes.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

log = logging.getLogger(__name__)


class ControlApiError(Exception):
    """Non-success response or unreachable control plane (§8.3 storage_down
    semantics apply to the caller, not here)."""


@dataclass(frozen=True)
class Assignment:
    """One account this deployment wants online (GET /runtime/accounts row)."""

    account_id: str           # account uuid — lease/runner/job key
    api_row_id: int           # int id, only for uuid-scoped platform endpoints
    tenant_id: str            # tenant uuid (job rows carry uuid strings)
    project_id: str           # project uuid
    telegram_user_id: int | None
    observed_status: str
    has_session: bool


@dataclass(frozen=True)
class SessionBundle:
    """Session material for one account, held in memory only (§5.1)."""

    session_bytes: bytes
    api_id: int
    api_hash: str
    device_model: str | None = None
    app_version: str | None = None


@dataclass(frozen=True)
class CandidatePayload:
    content: str
    content_hash: str
    status: str


@dataclass(frozen=True)
class PendingCommand:
    id: int
    type: str
    dedup_key: str
    payload: dict[str, Any] = field(default_factory=dict)
    expected_generation: int | None = None


class ControlClient:
    def __init__(self, base_url: str, token: str, *, timeout_s: float = 15.0):
        if not token:
            raise ValueError("RUNTIME_WORKER_TOKEN is empty")
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"x-worker-token": token},
            timeout=timeout_s,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str) -> Any:
        r = await self._http.get(path)
        return self._unwrap(r)

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        r = await self._http.post(path, json=body)
        return self._unwrap(r)

    @staticmethod
    def _unwrap(r: httpx.Response) -> Any:
        if r.status_code >= 400:
            raise ControlApiError(f"HTTP {r.status_code}: {r.text[:200]}")
        body = r.json()
        if isinstance(body, dict) and "data" in body:
            if body.get("code") not in (None, 0, 200):
                raise ControlApiError(f"code={body.get('code')} {body.get('msg')}")
            return body["data"]
        return body

    async def list_accounts(self) -> list[Assignment]:
        rows = await self._get("/accounts")
        return [
            Assignment(
                account_id=r["uuid"], api_row_id=r["id"],
                tenant_id=r["tenant_uuid"], project_id=r["project_uuid"],
                telegram_user_id=r.get("telegram_user_id"),
                observed_status=r["observed_status"],
                has_session=r["has_session"],
            )
            for r in rows
        ]

    async def fetch_session(self, account_uuid: str) -> SessionBundle:
        d = await self._get(f"/accounts/{account_uuid}/session")
        meta = d.get("meta") or {}
        if meta.get("app_id") is None or not meta.get("app_hash"):
            raise ControlApiError(f"session meta missing app_id/app_hash for {account_uuid}")
        return SessionBundle(
            session_bytes=base64.b64decode(d["session_b64"]),
            api_id=int(meta["app_id"]),
            api_hash=meta["app_hash"],
            device_model=meta.get("device"),
            app_version=meta.get("app_version"),
        )

    async def pull_rules(self, api_row_id: int) -> list[dict[str, Any]]:
        return await self._get(f"/accounts/{api_row_id}/rules")

    async def pull_commands(self, api_row_id: int) -> list[PendingCommand]:
        rows = await self._get(f"/accounts/{api_row_id}/commands")
        return [
            PendingCommand(
                id=r["id"], type=r["type"], dedup_key=r.get("dedup_key") or "",
                payload=r.get("payload") or {},
                expected_generation=r.get("expected_generation"),
            )
            for r in rows
        ]

    async def ack_command(self, command_id: int, status: str, result: str = "") -> None:
        # status: acknowledged | done | rejected
        await self._post(f"/commands/{command_id}/ack",
                         {"status": status, "result": result[:500]})

    async def notify_ai_event(self, payload: dict[str, Any]) -> None:
        """Best-effort group-message report for AI 炒群 triggers (fire-and-forget)."""
        await self._post("/ai/event", payload)

    async def get_candidate(self, candidate_uuid: str) -> CandidatePayload:
        d = await self._get(f"/candidates/{candidate_uuid}")
        return CandidatePayload(
            content=d["content"], content_hash=d["content_hash"],
            status=d["status"],
        )

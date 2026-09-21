"""Lease heartbeat loop (§5.3): renew the account lease every `interval_s`
(starting point 10s against a 45s TTL). Losing the lease — or any storage
failure — invokes on_lost exactly once, then the loop exits; the worker must
stop claiming new sends for that account (§5.3, §8.3 storage_down)."""

from __future__ import annotations

import asyncio
import enum
from typing import Awaitable, Callable


class HeartbeatState(enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    LOST = "lost"       # renew returned False or raised — ownership gone
    STOPPED = "stopped"  # explicit stop


RenewFn = Callable[[], Awaitable[bool]]
LostFn = Callable[[str], None]


class LeaseHeartbeat:
    def __init__(self, renew: RenewFn, *, interval_s: float = 10.0,
                 on_lost: LostFn | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep):
        self._renew = renew
        self._interval = interval_s
        self._on_lost = on_lost or (lambda _reason: None)
        self._sleep = sleep
        self.state = HeartbeatState.IDLE
        self.renew_count = 0

    async def tick(self) -> bool:
        """One renewal round. Returns False when ownership is lost."""
        try:
            ok = await self._renew()
        except Exception as exc:  # storage down counts as lost (§8.3)
            ok, reason = False, f"renew_error:{type(exc).__name__}"
        else:
            reason = "lease_lost"
        if ok:
            self.renew_count += 1
            return True
        self.state = HeartbeatState.LOST
        self._on_lost(reason)
        return False

    async def run(self) -> HeartbeatState:
        self.state = HeartbeatState.RUNNING
        while self.state is HeartbeatState.RUNNING:
            if not await self.tick():
                break
            await self._sleep(self._interval)
        if self.state is HeartbeatState.RUNNING:  # pragma: no cover
            self.state = HeartbeatState.STOPPED
        return self.state

    def stop(self) -> None:
        if self.state is HeartbeatState.RUNNING:
            self.state = HeartbeatState.STOPPED

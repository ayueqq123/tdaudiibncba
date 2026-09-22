"""Worker entrypoint: `python -m runtime.worker`.

Env:
  DATABASE_URL           postgres+asyncpg DSN (shared control/runtime schema)
  RUNTIME_CONTROL_API    platform runtime base, e.g. http://control-api:8000/api/v1/tg/runtime
  RUNTIME_WORKER_TOKEN   shared service credential (X-Worker-Token)
  WORKER_ID              stable worker identity (lease owner; default hostname)
  WORKER_POLL_S          control poll + runner cadence (default 2.0)
  LEASE_TTL_S / LEASE_HEARTBEAT_S   lease timings (45 / 10)
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket

from runtime.storage.db import make_engine, make_session_factory
from runtime.worker.control_client import ControlClient
from runtime.worker.host import WorkerHostMain

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("runtime.worker")


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None or v == "":
        raise SystemExit(f"missing env {name}")
    return v


async def _main() -> None:
    database_url = _env("DATABASE_URL")
    control = ControlClient(
        _env("RUNTIME_CONTROL_API"), _env("RUNTIME_WORKER_TOKEN"))
    engine = make_engine(database_url)
    factory = make_session_factory(engine)

    host = WorkerHostMain(
        _env("WORKER_ID", socket.gethostname()),
        factory, control,
        lease_ttl_s=float(os.environ.get("LEASE_TTL_S", "45")),
        heartbeat_s=float(os.environ.get("LEASE_HEARTBEAT_S", "10")),
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, host.stop)
        except NotImplementedError:  # non-unix platforms
            pass

    log.info("worker %s starting, control=%s", host.worker_id,
             _env("RUNTIME_CONTROL_API"))
    try:
        await host.run(poll_s=float(os.environ.get("WORKER_POLL_S", "2")))
    finally:
        await control.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())

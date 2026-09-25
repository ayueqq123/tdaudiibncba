"""Phone verification-code login → produces an authorized Telethon SQLite session.

Two-step CLI used by telegram-platform via subprocess (GPL boundary: spawned,
never imported). `send` creates a pending session file and requests the login
code; `signin` completes the login in the same session file. Secrets travel via
stdin JSON, never via argv or logs. Prints a single JSON result line to stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _client(args):
    from telethon import TelegramClient
    from telethon.sessions import SQLiteSession

    return TelegramClient(
        SQLiteSession(args.session),
        int(args.api_id),
        args.api_hash,
        device_model=args.device or None,
        app_version=args.app_version or None,
    )


async def _send(args) -> None:
    try:
        client = _client(args)
        await client.connect()
        try:
            result = await client.send_code_request(args.phone)
            _emit({"ok": True, "phone_code_hash": result.phone_code_hash})
        finally:
            await client.disconnect()
    except Exception as exc:  # noqa: BLE001 — classified below
        _emit({"ok": False, "error": _classify(exc)})


async def _signin(args) -> None:
    from telethon import errors as tg_errors

    try:
        payload = json.loads(sys.stdin.read() or "{}")
        code = payload.get("code") or ""
        password = payload.get("password") or None
        client = _client(args)
        await client.connect()
        try:
            try:
                user = await client.sign_in(
                    phone=args.phone, code=code, phone_code_hash=args.code_hash
                )
            except tg_errors.SessionPasswordNeededError:
                if not password:
                    _emit({"ok": False, "need_password": True})
                    return
                user = await client.sign_in(password=password)
            _emit(
                {
                    "ok": True,
                    "user_id": user.id,
                    "username": user.username,
                    "phone": user.phone,
                }
            )
        finally:
            await client.disconnect()
    except Exception as exc:  # noqa: BLE001
        _emit({"ok": False, "error": _classify(exc)})


def _classify(exc: BaseException) -> dict:
    from telethon import errors as tg_errors

    table = (
        (tg_errors.PhoneNumberInvalidError, "phone_invalid"),
        (tg_errors.PhoneCodeInvalidError, "code_invalid"),
        (tg_errors.PhoneCodeExpiredError, "code_expired"),
        (tg_errors.PhoneNumberBannedError, "phone_banned"),
        (tg_errors.PhoneNumberUnoccupiedError, "phone_unoccupied"),
    )
    for exc_type, status in table:
        if isinstance(exc, exc_type):
            return {"status": status}
    if isinstance(exc, tg_errors.FloodWaitError):
        return {"status": "flood_wait", "seconds": exc.seconds}
    return {"status": "error", "detail": str(exc)[:300]}


def main() -> None:
    parser = argparse.ArgumentParser(prog="code_login")
    sub = parser.add_subparsers(dest="mode", required=True)
    for name in ("send", "signin"):
        p = sub.add_parser(name)
        p.add_argument("--session", required=True)
        p.add_argument("--api-id", required=True)
        p.add_argument("--api-hash", required=True)
        p.add_argument("--phone", required=True)
        p.add_argument("--device", default=None)
        p.add_argument("--app-version", default=None)
        if name == "signin":
            p.add_argument("--code-hash", required=True)
    args = parser.parse_args()
    Path(args.session).parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_send(args) if args.mode == "send" else _signin(args))


if __name__ == "__main__":
    main()

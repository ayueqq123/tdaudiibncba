"""Bulk session (协议号) import: package parsing + minimal-connectivity validation.

Implements architecture doc §5.1.1. Validation performs connect + getMe ONLY —
no message reads, no sends. Session contents never enter logs or results beyond
status codes and public identity fields.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

logger = logging.getLogger(__name__)

SQLITE_MAGIC = b"SQLite format 3\x00"


class SessionFormat(enum.Enum):
    SQLITE = "sqlite"
    STRING = "string"
    TDATA = "tdata"
    UNKNOWN = "unknown"


class ImportStatus(enum.Enum):
    VERIFIED = "verified"
    AUTH_FAILED = "auth_failed"
    TWOFA_LOCKED = "2fa_locked"
    SPAMBLOCKED = "spamblocked"
    DEACTIVATED = "deactivated"
    INVALID_FORMAT = "invalid_format"
    ERROR = "error"


@dataclass
class ImportItem:
    """One imported account candidate: a session plus its optional metadata."""

    key: str
    session_path: Path
    fmt: SessionFormat
    meta: dict[str, Any] = field(default_factory=dict)
    meta_path: Path | None = None


@dataclass
class ValidationResult:
    key: str
    status: ImportStatus
    user_id: int | None = None
    username: str | None = None
    premium: bool | None = None
    two_fa: bool | None = None
    spamblock: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is ImportStatus.VERIFIED


def detect_format(path: Path) -> SessionFormat:
    if path.is_dir():
        return SessionFormat.TDATA
    try:
        head = path.read_bytes()[:4096]
    except OSError:
        return SessionFormat.UNKNOWN
    if head.startswith(SQLITE_MAGIC):
        return SessionFormat.SQLITE
    try:
        text = head.decode("ascii").strip()
    except UnicodeDecodeError:
        return SessionFormat.UNKNOWN
    if text and all(c.isalnum() or c in "-_" for c in text):
        return SessionFormat.STRING
    return SessionFormat.UNKNOWN


def _load_meta(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def parse_directory(directory: Path) -> list[ImportItem]:
    """Pair `<stem>.session` files with `<stem>.json` metadata in a directory."""
    items: list[ImportItem] = []
    for session_path in sorted(directory.rglob("*.session")):
        meta_path = session_path.with_suffix(".json")
        items.append(
            ImportItem(
                key=session_path.stem,
                session_path=session_path,
                fmt=detect_format(session_path),
                meta=_load_meta(meta_path),
                meta_path=meta_path if meta_path.exists() else None,
            )
        )
    return items


def parse_package(path: Path) -> list[ImportItem]:
    """Accept a zip batch package or an already-extracted directory."""
    if path.is_dir():
        return parse_directory(path)
    if zipfile.is_zipfile(path):
        import tempfile

        dest = Path(tempfile.mkdtemp(prefix="session-import-"))
        with zipfile.ZipFile(path) as zf:
            zf.extractall(dest)
        return parse_directory(dest)
    return []


def _classify_error(exc: BaseException) -> ImportStatus:
    from telethon import errors as tg_errors

    mapping: tuple[tuple[type[BaseException], ImportStatus], ...] = (
        (tg_errors.SessionPasswordNeededError, ImportStatus.TWOFA_LOCKED),
        (tg_errors.UserDeactivatedError, ImportStatus.DEACTIVATED),
        (tg_errors.UserDeactivatedBanError, ImportStatus.DEACTIVATED),
        (tg_errors.PhoneNumberBannedError, ImportStatus.DEACTIVATED),
        (tg_errors.AuthKeyError, ImportStatus.AUTH_FAILED),
        (tg_errors.AuthKeyUnregisteredError, ImportStatus.AUTH_FAILED),
    )
    for exc_type, status in mapping:
        if isinstance(exc, exc_type):
            return status
    return ImportStatus.ERROR


def _build_client(item: ImportItem):
    """Client fingerprint comes from the package metadata, not platform defaults —
    a fingerprint mismatch is the most common ban trigger for imported sessions."""
    from telethon import TelegramClient
    from telethon.sessions import SQLiteSession

    meta = item.meta
    api_id = meta.get("app_id")
    api_hash = meta.get("app_hash")
    if api_id is None or not api_hash:
        raise ValueError("meta missing app_id/app_hash")
    return TelegramClient(
        SQLiteSession(str(item.session_path)),
        int(api_id),
        api_hash,
        device_model=meta.get("device") or None,
        app_version=str(meta.get("app_version") or "") or None,
        lang_code="en",
    )


async def validate_item(
    item: ImportItem,
    *,
    timeout: float = 25.0,
    client_factory: Callable[[ImportItem], Any] | None = None,
) -> ValidationResult:
    """connect + getMe minimal validation. Never reads or sends messages."""
    result = ValidationResult(
        key=item.key,
        status=ImportStatus.ERROR,
        two_fa=bool(item.meta.get("twoFA")) if "twoFA" in item.meta else None,
        spamblock=item.meta.get("spamblock"),
    )
    if item.fmt is not SessionFormat.SQLITE:
        result.status = ImportStatus.INVALID_FORMAT
        result.detail = f"unsupported format: {item.fmt.value}"
        return result
    if not item.meta:
        result.status = ImportStatus.INVALID_FORMAT
        result.detail = "missing json metadata (app_id/app_hash required)"
        return result

    factory = client_factory or _build_client
    client = None
    try:
        client = factory(item)
        await asyncio.wait_for(client.connect(), timeout=timeout)
        if not await client.is_user_authorized():
            result.status = ImportStatus.TWOFA_LOCKED if result.two_fa else ImportStatus.AUTH_FAILED
            return result
        me = await asyncio.wait_for(client.get_me(), timeout=timeout)
        result.status = ImportStatus.VERIFIED
        result.user_id = me.id
        result.username = getattr(me, "username", None)
        result.premium = getattr(me, "premium", None)
        return result
    except asyncio.TimeoutError:
        result.status = ImportStatus.ERROR
        result.detail = f"timeout after {timeout}s"
        return result
    except ValueError as exc:
        result.status = ImportStatus.INVALID_FORMAT
        result.detail = str(exc)
        return result
    except Exception as exc:  # telethon errors -> classified status
        result.status = _classify_error(exc)
        if result.status is ImportStatus.ERROR:
            result.detail = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass


async def validate_package(
    items: Iterable[ImportItem],
    *,
    delay: float = 2.0,
    timeout: float = 25.0,
    client_factory: Callable[[ImportItem], Any] | None = None,
    on_item: Callable[[ValidationResult], None] | None = None,
) -> list[ValidationResult]:
    """Validate items sequentially with a fixed stagger — never burst-login a batch."""
    results: list[ValidationResult] = []
    first = True
    for item in items:
        if not first:
            await asyncio.sleep(delay)
        first = False
        result = await validate_item(item, timeout=timeout, client_factory=client_factory)
        results.append(result)
        if on_item is not None:
            on_item(result)
    return results


def _format_result(r: ValidationResult) -> str:
    parts = [r.key, r.status.value.upper()]
    if r.user_id is not None:
        parts.append(f"user_id={r.user_id}")
    if r.username:
        parts.append(f"@{r.username}")
    if r.two_fa:
        parts.append("twoFA")
    if r.spamblock:
        parts.append(f"spamblock={r.spamblock}")
    if r.detail:
        parts.append(f"({r.detail})")
    return " ".join(parts)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate a session import package")
    parser.add_argument("package", type=Path)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=25.0)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    items = parse_package(args.package)
    if not items:
        print("no .session files found")
        return 2
    print(f"{len(items)} session(s) found")

    results = asyncio.run(validate_package(items, delay=args.delay, timeout=args.timeout,
                                           on_item=lambda r: print(_format_result(r), flush=True)))
    ok = sum(1 for r in results if r.ok)
    print(f"{ok}/{len(results)} verified")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

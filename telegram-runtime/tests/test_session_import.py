"""Unit tests for runtime.account.session_import. No real network access."""

import asyncio
import json
import sqlite3
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from runtime.account.session_import import (
    ImportItem,
    ImportStatus,
    SessionFormat,
    detect_format,
    parse_directory,
    parse_package,
    validate_item,
)


def _make_sqlite_session(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sessions (dc_id INTEGER, server_address TEXT, port INTEGER, auth_key BLOB)"
    )
    conn.commit()
    conn.close()


def _meta(**overrides):
    base = {"app_id": 12345, "app_hash": "x" * 32, "device": "Test Device"}
    base.update(overrides)
    return base


@pytest.fixture()
def pkg_dir(tmp_path: Path) -> Path:
    for phone in ("254100000001", "254100000002"):
        _make_sqlite_session(tmp_path / f"{phone}.session")
        (tmp_path / f"{phone}.json").write_text(json.dumps(_meta(phone=phone)))
    (tmp_path / "readme.txt").write_text("not a session")
    return tmp_path


def test_detect_format_sqlite(tmp_path: Path):
    p = tmp_path / "a.session"
    _make_sqlite_session(p)
    assert detect_format(p) is SessionFormat.SQLITE


def test_detect_format_string_session(tmp_path: Path):
    p = tmp_path / "a.session"
    p.write_text("1BJhb21tZW4uY29tABCDEFGH")
    assert detect_format(p) is SessionFormat.STRING


def test_detect_format_unknown_and_dir(tmp_path: Path):
    p = tmp_path / "blob.session"
    p.write_bytes(b"\x00\xff\x00\xff binary junk")
    assert detect_format(p) is SessionFormat.UNKNOWN
    assert detect_format(tmp_path) is SessionFormat.TDATA


def test_parse_directory_pairs_meta(pkg_dir: Path):
    items = parse_directory(pkg_dir)
    assert len(items) == 2
    assert all(i.fmt is SessionFormat.SQLITE for i in items)
    assert all(i.meta.get("app_id") == 12345 for i in items)


def test_parse_directory_unpaired_session(tmp_path: Path):
    _make_sqlite_session(tmp_path / "lonely.session")
    items = parse_directory(tmp_path)
    assert len(items) == 1
    assert items[0].meta == {}


def test_parse_package_zip(pkg_dir: Path, tmp_path: Path):
    zpath = tmp_path / "batch.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in pkg_dir.iterdir():
            zf.write(f, f.name)
    items = parse_package(zpath)
    assert len(items) == 2


class FakeClient:
    def __init__(self, authorized=True, me=None, connect_exc=None):
        self._authorized = authorized
        self._me = me
        self._connect_exc = connect_exc
        self.disconnected = False

    async def connect(self):
        if self._connect_exc:
            raise self._connect_exc

    async def is_user_authorized(self):
        return self._authorized

    async def get_me(self):
        return self._me

    async def disconnect(self):
        self.disconnected = True


def _item(tmp_path: Path, **meta_overrides) -> ImportItem:
    p = tmp_path / "254100000099.session"
    _make_sqlite_session(p)
    return ImportItem(key="254100000099", session_path=p,
                      fmt=SessionFormat.SQLITE, meta=_meta(**meta_overrides))


def _run(coro):
    return asyncio.run(coro)


def test_validate_verified(tmp_path: Path):
    me = MagicMock(id=987654321, username="tester", premium=False)
    client = FakeClient(authorized=True, me=me)
    r = _run(validate_item(_item(tmp_path), client_factory=lambda i: client))
    assert r.status is ImportStatus.VERIFIED
    assert r.user_id == 987654321 and r.username == "tester"
    assert client.disconnected


def test_validate_auth_failed(tmp_path: Path):
    r = _run(validate_item(_item(tmp_path), client_factory=lambda i: FakeClient(authorized=False)))
    assert r.status is ImportStatus.AUTH_FAILED


def test_validate_twofa_locked_when_unauthorized_with_flag(tmp_path: Path):
    r = _run(validate_item(_item(tmp_path, twoFA="8899"),
                           client_factory=lambda i: FakeClient(authorized=False)))
    assert r.status is ImportStatus.TWOFA_LOCKED
    assert r.two_fa is True


def test_validate_invalid_format(tmp_path: Path):
    item = _item(tmp_path)
    item.fmt = SessionFormat.UNKNOWN
    r = _run(validate_item(item, client_factory=lambda i: FakeClient()))
    assert r.status is ImportStatus.INVALID_FORMAT


def test_validate_missing_meta(tmp_path: Path):
    item = _item(tmp_path)
    item.meta = {}
    r = _run(validate_item(item, client_factory=lambda i: FakeClient()))
    assert r.status is ImportStatus.INVALID_FORMAT


def test_validate_deactivated_error(tmp_path: Path):
    from telethon import errors

    client = FakeClient(connect_exc=errors.UserDeactivatedError(request=None))
    r = _run(validate_item(_item(tmp_path), client_factory=lambda i: client))
    assert r.status is ImportStatus.DEACTIVATED


def test_validate_timeout(tmp_path: Path):
    class SlowClient(FakeClient):
        async def connect(self):
            await asyncio.sleep(5)

    r = _run(validate_item(_item(tmp_path), timeout=0.05, client_factory=lambda i: SlowClient()))
    assert r.status is ImportStatus.ERROR
    assert "timeout" in r.detail

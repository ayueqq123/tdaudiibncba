from types import SimpleNamespace

import pytest
from telethon.tl.types import User

from runtime.worker.live import _SENDER_BOT, _resolve_sender_bot, _sender_is_bot


@pytest.fixture(autouse=True)
def clear_sender_bot_cache():
    _SENDER_BOT.clear()


def _user(bot: bool, username: str | None = None) -> User:
    return User(id=7, first_name="Test", bot=bot, username=username)


@pytest.mark.asyncio
async def test_resolves_bot_when_sender_is_not_cached():
    async def get_sender():
        return _user(bot=True)

    msg = SimpleNamespace(sender_id=7, sender=None, get_sender=get_sender)
    await _resolve_sender_bot(msg)
    assert _sender_is_bot(msg) is True


@pytest.mark.asyncio
async def test_sender_resolution_failure_is_not_cached_and_can_retry():
    async def get_sender():
        raise RuntimeError("unavailable")

    msg = SimpleNamespace(sender_id=7, sender=None, get_sender=get_sender)
    await _resolve_sender_bot(msg)
    assert _sender_is_bot(msg) is False
    assert 7 not in _SENDER_BOT

    async def get_sender_successfully():
        return _user(bot=True)

    msg.get_sender = get_sender_successfully
    await _resolve_sender_bot(msg)
    assert _sender_is_bot(msg) is True
    assert _SENDER_BOT[7] is True


@pytest.mark.asyncio
async def test_cached_bot_status_avoids_sender_resolution():
    _SENDER_BOT[7] = True
    calls = 0

    async def get_sender():
        nonlocal calls
        calls += 1
        return _user(bot=False)

    msg = SimpleNamespace(sender_id=7, sender=None, get_sender=get_sender)
    await _resolve_sender_bot(msg)
    assert _sender_is_bot(msg) is True
    assert calls == 0


@pytest.mark.asyncio
async def test_cached_sender_entity_is_recorded_without_resolution():
    async def get_sender():
        raise AssertionError("get_sender must not be called")

    msg = SimpleNamespace(sender_id=7, sender=_user(bot=False), get_sender=get_sender)
    await _resolve_sender_bot(msg)
    assert _sender_is_bot(msg) is False
    assert _SENDER_BOT[7] is False


@pytest.mark.asyncio
async def test_negative_sender_id_skips_resolution():
    async def get_sender():
        raise AssertionError("get_sender must not be called")

    msg = SimpleNamespace(sender_id=-1007, sender=None, get_sender=get_sender)
    await _resolve_sender_bot(msg)
    assert _sender_is_bot(msg) is False
    assert _SENDER_BOT == {}


def test_via_bot_id_is_bot():
    msg = SimpleNamespace(sender_id=7, sender=None, via_bot_id=88)
    assert _sender_is_bot(msg) is True

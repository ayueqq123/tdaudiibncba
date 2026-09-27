"""Membership probe + UpdateChannel watcher (kicked accounts only get a bare UpdateChannel)."""

import asyncio

from telethon.errors import ChannelPrivateError, UserNotParticipantError
from telethon.tl import types as tl

from runtime.worker.live import check_membership, register_membership_watch


class ProbeClient:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0
        self.handlers = []

    async def get_input_entity(self, chat_id):
        return tl.InputPeerChannel(abs(chat_id) % 10**10, 0)

    async def __call__(self, request):
        self.calls += 1
        if self.error:
            raise self.error(request=request)
        return object()

    def add_event_handler(self, fn, ev):
        self.handlers.append(fn)


class Sess:
    def __init__(self, client):
        self.client = client


def test_check_membership_outcomes():
    assert asyncio.run(check_membership(ProbeClient(), -1001234)) is None
    assert asyncio.run(check_membership(ProbeClient(ChannelPrivateError), -1001234)) == "kicked"
    assert asyncio.run(check_membership(ProbeClient(UserNotParticipantError), -1001234)) == "not_member"
    basic = ProbeClient(ChannelPrivateError)
    assert asyncio.run(check_membership(basic, -4567)) is None
    assert basic.calls == 0


def test_watch_reports_only_watched_lost_chats():
    client = ProbeClient(ChannelPrivateError)
    lost = []

    async def on_lost(chat_id, reason):
        lost.append((chat_id, reason))

    register_membership_watch(Sess(client), lambda: {-1000000001234}, on_lost)
    handler = client.handlers[0]
    asyncio.run(handler(tl.UpdateChannel(channel_id=999)))
    asyncio.run(handler(tl.UpdateNewChannelMessage(message=None, pts=1, pts_count=1)))
    assert lost == [] and client.calls == 0
    asyncio.run(handler(tl.UpdateChannel(channel_id=1234)))
    assert lost == [(-1000000001234, "kicked")]

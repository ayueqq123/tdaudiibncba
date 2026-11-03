from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from runtime.worker import live
from runtime.planner.model import EventKind


class _Event:
    def __init__(self, message, chat=None, chat_id=100):
        self.message = message
        self.chat = chat
        self.chat_id = chat_id


class _NewMessageEvent(_Event):
    pass


class _MessageEditedEvent(_Event):
    pass


@pytest.fixture
def fake_event_types(monkeypatch):
    monkeypatch.setattr(
        live,
        "events",
        SimpleNamespace(
            NewMessage=SimpleNamespace(Event=_NewMessageEvent),
            MessageEdited=SimpleNamespace(Event=_MessageEditedEvent),
            MessageDeleted=SimpleNamespace(Event=type("_MessageDeletedEvent", (), {})),
        ),
    )


def _message(date, edit_date=None):
    return SimpleNamespace(
        id=123,
        peer_id=None,
        date=date,
        edit_date=edit_date,
        reply_to=None,
        message="test message",
        grouped_id=456,
        noforwards=False,
        sender_id=None,
        sender=None,
    )


def test_recent_message_edit_emits_create_then_edit(fake_event_types):
    now = datetime.now(UTC)
    edit_date = now - timedelta(seconds=2)
    event = _MessageEditedEvent(_message(now - timedelta(seconds=2), edit_date))

    raws = live._to_raws(event)

    assert [raw.kind for raw in raws] == [EventKind.CREATE, EventKind.EDIT]
    assert raws[0].edit_date_ts is None
    assert raws[1].edit_date_ts == int(edit_date.timestamp())
    assert raws[0].chat_id == raws[1].chat_id == 100
    assert raws[0].message_id == raws[1].message_id == 123
    assert raws[0].content_hash == raws[1].content_hash


def test_old_message_edit_emits_only_edit(fake_event_types):
    now = datetime.now(UTC)
    event = _MessageEditedEvent(
        _message(now - timedelta(hours=1), now - timedelta(seconds=2))
    )

    raws = live._to_raws(event)

    assert len(raws) == 1
    assert raws[0].kind is EventKind.EDIT
    assert raws[0].edit_date_ts == int((now - timedelta(seconds=2)).timestamp())


def test_new_message_emits_create(fake_event_types):
    event = _NewMessageEvent(_message(datetime.now(UTC)))

    raws = live._to_raws(event)

    assert len(raws) == 1
    assert raws[0].kind is EventKind.CREATE


@pytest.mark.asyncio
async def test_message_edit_does_not_notify_ai(fake_event_types, monkeypatch):
    ingested = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class InboxRepository:
        def __init__(self, session):
            pass

        async def ingest(self, event, *, tenant_id, project_id):
            ingested.append(event)

    class Control:
        def __init__(self):
            self.notifications = []

        async def notify_ai_event(self, payload):
            self.notifications.append(payload)

    monkeypatch.setattr(live, "EventInboxRepository", InboxRepository)
    control = Control()
    handler = live.make_ingest_handler(
        Session, "account-1", "tenant-1", "project-1",
        control=control, api_row_id=1,
    )
    event = _MessageEditedEvent(_message(datetime.now(UTC)))

    await handler(event)

    assert [item.kind for item in ingested] == [EventKind.CREATE, EventKind.EDIT]
    assert control.notifications == []

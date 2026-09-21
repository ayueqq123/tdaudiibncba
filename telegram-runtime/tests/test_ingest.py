"""Tests for runtime.ingest normalizer + album aggregator."""

from runtime.ingest.album import AlbumAggregator, MemberDisposition
from runtime.ingest.normalizer import (
    ChatClass,
    EventNormalizer,
    RawUpdate,
    dedup_key,
    event_revision,
    source_scope_for,
)
from runtime.planner.model import EventKind


def _raw(**kw):
    base = dict(kind=EventKind.CREATE, chat_id=100, message_id=1,
                chat_class=ChatClass.BROADCAST)
    base.update(kw)
    return RawUpdate(**base)


def test_broadcast_scope_is_canonical():
    assert source_scope_for(ChatClass.BROADCAST, 100, "a1") == "peer:100"


def test_small_group_scope_embeds_account():
    assert source_scope_for(ChatClass.SMALL_GROUP, 100, "a1") == "peer:100:acct:a1"
    assert source_scope_for(ChatClass.SMALL_GROUP, 100, "a2") != source_scope_for(
        ChatClass.SMALL_GROUP, 100, "a1")


def test_normalizer_fields_and_protected():
    ev = EventNormalizer().normalize(
        _raw(protected=True, grouped_id=77, reply_to_message_id=9, topic_id=3),
        account_id="acct-1")
    assert ev.protected and ev.grouped_id == 77
    assert ev.reply_to_source_id == 9 and ev.topic_id == 3
    assert ev.revision == 1


def test_edit_revision_uses_platform_ts():
    ev = EventNormalizer().normalize(
        _raw(kind=EventKind.EDIT, edit_date_ts=1727000000), "a1")
    assert ev.revision == 1727000000


def test_delete_revision_dominates():
    create = event_revision(EventKind.CREATE, _raw())
    delete = event_revision(EventKind.DELETE, _raw(kind=EventKind.DELETE))
    edit = event_revision(EventKind.EDIT, _raw(kind=EventKind.EDIT, edit_date_ts=1727000000))
    assert delete > edit > create


def test_dedup_key_is_per_kind_and_revision():
    n = EventNormalizer()
    a = n.normalize(_raw(), "a1")
    b = n.normalize(_raw(kind=EventKind.EDIT, edit_date_ts=99), "a1")
    assert dedup_key(a) != dedup_key(b)
    assert dedup_key(a) == dedup_key(n.normalize(_raw(), "a1"))


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_album_window_collects_and_closes():
    clock = Clock()
    agg = AlbumAggregator(window_s=1.0, now=clock)
    g, disp = agg.add("a1", 100, 55, 1)
    assert disp is MemberDisposition.IN_GROUP and g is None
    g, disp = agg.add("a1", 100, 55, 3)
    assert g is None
    clock.t = 1.5
    g, disp = agg.add("a1", 100, 55, 2)
    assert disp is MemberDisposition.IN_GROUP and g is not None
    assert g.members == [1, 2, 3]  # sorted on close


def test_album_late_member_flagged():
    clock = Clock()
    agg = AlbumAggregator(window_s=1.0, now=clock)
    agg.add("a1", 100, 55, 1)
    clock.t = 2.0
    closed = agg.flush()
    assert len(closed) == 1 and closed[0].members == [1]
    g, disp = agg.add("a1", 100, 55, 2)
    assert g is None and disp is MemberDisposition.LATE


def test_album_scopes_by_account_and_chat():
    clock = Clock()
    agg = AlbumAggregator(window_s=1.0, now=clock)
    agg.add("a1", 100, 55, 1)
    agg.add("a2", 100, 55, 9)   # different account, same grouped_id
    agg.add("a1", 200, 55, 5)   # different chat
    clock.t = 2.0
    closed = agg.flush()
    by_key = {g.key: g.members for g in closed}
    assert by_key[("a1", 100, 55)] == [1]
    assert by_key[("a2", 100, 55)] == [9]
    assert by_key[("a1", 200, 55)] == [5]

"""Tests for runtime.planner.ClonePlanner. Pure logic, no network."""

import pytest

from runtime.planner.model import (
    ApprovalPolicy,
    CloneMode,
    EventKind,
    PlanKind,
    RuleSnapshot,
    RouteTarget,
    SourceEvent,
)
from runtime.planner.planner import ClonePlanner


class DictMapping:
    def __init__(self, entries=None):
        self.entries = entries or {}

    def find_target_message_id(self, route_id, scope, chat, msg):
        return self.entries.get((route_id, scope, chat, msg))


def _event(**kw):
    base = dict(
        kind=EventKind.CREATE, source_scope="peer", source_chat_id=100,
        source_message_id=1, revision=1, account_id="acct-1",
    )
    base.update(kw)
    return SourceEvent(**base)


def _rule(**kw):
    base = dict(
        rule_id="r1", version=3, account_id="acct-1", source_scope="peer",
        source_chat_id=100, source_topic_id=None,
        targets=(RouteTarget(route_id="rt-1", target_chat_id=200),
                 RouteTarget(route_id="rt-2", target_chat_id=300)),
        mode=CloneMode.COPY, sync_edit=True, sync_delete=True,
    )
    base.update(kw)
    return RuleSnapshot(**base)


def test_create_fans_out_per_route():
    p = ClonePlanner(DictMapping()).plan(_event(), [_rule()])
    assert len(p) == 2
    assert {x.route_id for x in p} == {"rt-1", "rt-2"}
    assert all(x.kind is PlanKind.SEND for x in p)
    assert all(x.rule_version == 3 for x in p)
    assert len({x.idempotency_key for x in p}) == 2


def test_wrong_account_or_chat_skipped():
    p = ClonePlanner(DictMapping())
    assert p.plan(_event(), [_rule(account_id="other")]) == []
    assert p.plan(_event(), [_rule(source_chat_id=999)]) == []


def test_topic_scoped_rule():
    rule = _rule(source_topic_id=42)
    p = ClonePlanner(DictMapping())
    assert p.plan(_event(topic_id=42), [rule]) != []
    assert p.plan(_event(topic_id=7), [rule]) == []
    assert p.plan(_event(topic_id=None), [rule]) == []


def test_protected_source_never_planned():
    p = ClonePlanner(DictMapping()).plan(_event(protected=True), [_rule()])
    assert p == []


def test_edit_respects_sync_and_forward():
    p = ClonePlanner(DictMapping())
    ev = _event(kind=EventKind.EDIT, revision=2)
    assert [x.kind for x in p.plan(ev, [_rule()])] == [PlanKind.EDIT] * 2
    assert p.plan(ev, [_rule(sync_edit=False)]) == []
    assert p.plan(ev, [_rule(mode=CloneMode.FORWARD)]) == []  # forward can't edit


def test_delete_respects_sync():
    p = ClonePlanner(DictMapping())
    ev = _event(kind=EventKind.DELETE)
    assert [x.kind for x in p.plan(ev, [_rule()])] == [PlanKind.DELETE] * 2
    assert p.plan(ev, [_rule(sync_delete=False)]) == []


def test_message_review_only_on_send():
    rule = _rule(approval_policy=ApprovalPolicy.MESSAGE_REVIEW)
    p = ClonePlanner(DictMapping())
    create = p.plan(_event(), [rule])
    assert all(x.requires_approval for x in create)
    delete = p.plan(_event(kind=EventKind.DELETE), [rule])
    assert all(not x.requires_approval for x in delete)


def test_reply_resolution_via_mapping():
    mapping = DictMapping({("rt-1", "peer", 100, 50): 9001})
    ev = _event(reply_to_source_id=50)
    plans = ClonePlanner(mapping).plan(ev, [_rule()])
    by_route = {x.route_id: x for x in plans}
    assert by_route["rt-1"].reply_to_target_message_id == 9001
    assert by_route["rt-2"].reply_to_target_message_id is None


def test_sender_user_ids_whitelist():
    p = ClonePlanner(DictMapping())
    rule = _rule(filters=({"sender_user_ids": [111, 222]},))
    assert p.plan(_event(sender_id=111), [rule]) != []
    assert p.plan(_event(sender_id=333), [rule]) == []
    # anonymous/service posts carry no sender -> filtered out
    assert p.plan(_event(sender_id=None), [rule]) == []


def test_no_whitelist_passes_all_senders():
    p = ClonePlanner(DictMapping())
    for filters in ((), ({},), ({"sender_user_ids": []},)):
        assert p.plan(_event(sender_id=333), [_rule(filters=filters)]) != []
        assert p.plan(_event(sender_id=None), [_rule(filters=filters)]) != []


def test_whitelist_does_not_block_edit_or_delete():
    p = ClonePlanner(DictMapping())
    rule = _rule(filters=({"sender_user_ids": [111]},))
    ev_edit = _event(kind=EventKind.EDIT, revision=2, sender_id=333)
    assert [x.kind for x in p.plan(ev_edit, [rule])] == [PlanKind.EDIT] * 2
    ev_del = _event(kind=EventKind.DELETE, sender_id=None)
    assert [x.kind for x in p.plan(ev_del, [rule])] == [PlanKind.DELETE] * 2


def test_media_kinds_whitelist():
    p = ClonePlanner(DictMapping())
    rule = _rule(filters=({"media_kinds": ["photo", "text"]},))
    assert p.plan(_event(media_kind="photo"), [rule]) != []
    assert p.plan(_event(media_kind="video"), [rule]) == []
    # untyped events count as text
    assert p.plan(_event(media_kind=None), [rule]) != []


def test_media_and_sender_filters_compose():
    p = ClonePlanner(DictMapping())
    rule = _rule(filters=({"sender_user_ids": [111], "media_kinds": ["photo"]},))
    assert p.plan(_event(sender_id=111, media_kind="photo"), [rule]) != []
    assert p.plan(_event(sender_id=111, media_kind="video"), [rule]) == []
    assert p.plan(_event(sender_id=222, media_kind="photo"), [rule]) == []


def test_exclude_bots_filter():
    p = ClonePlanner(DictMapping())
    rule = _rule(filters=({"exclude_bots": True},))
    assert p.plan(_event(sender_id=111, sender_is_bot=True), [rule]) == []
    assert p.plan(_event(sender_id=111), [rule]) != []
    assert p.plan(_event(sender_id=111, sender_is_bot=True), [_rule()]) != []


def test_blocked_sender_ids_blacklist():
    p = ClonePlanner(DictMapping())
    rule = _rule(filters=({"blocked_sender_ids": [111]},))
    assert p.plan(_event(sender_id=111), [rule]) == []
    assert p.plan(_event(sender_id=222), [rule]) != []
    assert p.plan(_event(sender_id=None), [rule]) != []
    ev_edit = _event(kind=EventKind.EDIT, revision=2, sender_id=111)
    assert p.plan(ev_edit, [rule]) != []

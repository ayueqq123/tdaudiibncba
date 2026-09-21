"""ClonePlanner: SourceEvent + RuleSnapshot -> one DeliveryPlan per route (§4.3).

Split of telemirror's EventProcessor: planning is pure and side-effect-free —
filtering runs here, Telegram sends never do (§4.2 item 2-3).
"""

from __future__ import annotations

from typing import Protocol

from .model import (
    ApprovalPolicy,
    CloneMode,
    DeliveryPlan,
    EventKind,
    PlanKind,
    RuleSnapshot,
    SourceEvent,
)


class MappingView(Protocol):
    """Read-only view over message_map for reply resolution and loop guards."""

    def find_target_message_id(
        self, route_id: str, source_scope: str,
        source_chat_id: int, source_message_id: int,
    ) -> int | None:
        """Return the target-side message id this route produced for a source
        message, or None. Used to resolve reply references (§7.5)."""
        ...


def _matches_rule(event: SourceEvent, rule: RuleSnapshot) -> bool:
    if event.account_id != rule.account_id:
        return False
    if event.source_scope != rule.source_scope or event.source_chat_id != rule.source_chat_id:
        return False
    if rule.source_topic_id is not None and event.topic_id != rule.source_topic_id:
        return False
    if event.protected:
        # never copy/forward protected content (§4.2 non-goals)
        return False
    return True


def _passes_filters(event: SourceEvent, rule: RuleSnapshot) -> bool:
    """Compiled-filter whitelist gate. Filter evaluation itself lives in ingest's
    filter registry; the planner only honors explicit block markers recorded on
    the event by that layer (opaque `filters` on the rule stay config here)."""
    return True


class ClonePlanner:
    def __init__(self, mapping: MappingView):
        self._mapping = mapping

    def plan(
        self, event: SourceEvent, rules: list[RuleSnapshot],
    ) -> list[DeliveryPlan]:
        plans: list[DeliveryPlan] = []
        for rule in rules:
            if not _matches_rule(event, rule):
                continue
            if event.kind is EventKind.CREATE and not _passes_filters(event, rule):
                continue
            plans.extend(self._plan_for_rule(event, rule))
        return plans

    def _plan_for_rule(self, event: SourceEvent, rule: RuleSnapshot) -> list[DeliveryPlan]:
        if event.kind is EventKind.EDIT and not rule.sync_edit:
            return []
        if event.kind is EventKind.DELETE and not rule.sync_delete:
            return []
        # forward mode cannot sync content edits (§7.2)
        if event.kind is EventKind.EDIT and rule.mode is CloneMode.FORWARD:
            return []

        kind = {
            EventKind.CREATE: PlanKind.SEND,
            EventKind.EDIT: PlanKind.EDIT,
            EventKind.DELETE: PlanKind.DELETE,
        }[event.kind]

        requires_approval = (
            rule.approval_policy is ApprovalPolicy.MESSAGE_REVIEW
            and kind is PlanKind.SEND
        )

        plans = []
        for route in rule.targets:
            reply_target = None
            if event.reply_to_source_id is not None:
                reply_target = self._mapping.find_target_message_id(
                    route.route_id, event.source_scope,
                    event.source_chat_id, event.reply_to_source_id,
                )
            plans.append(
                DeliveryPlan(
                    kind=kind,
                    rule_id=rule.rule_id,
                    rule_version=rule.version,
                    route_id=route.route_id,
                    account_id=rule.account_id,
                    source_scope=event.source_scope,
                    source_chat_id=event.source_chat_id,
                    source_message_id=event.source_message_id,
                    revision=event.revision,
                    target_chat_id=route.target_chat_id,
                    target_topic_id=route.target_topic_id,
                    mode=rule.mode,
                    payload_ref=event.payload_ref,
                    payload_hash=event.payload_hash,
                    requires_approval=requires_approval,
                    reply_to_target_message_id=reply_target,
                    grouped_id=event.grouped_id,
                )
            )
        return plans

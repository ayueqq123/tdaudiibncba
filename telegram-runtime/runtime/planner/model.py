"""Normalized source events and delivery planning types (§4.3, §7.1).

Pure data + pure planning logic: no Telethon, no DB. The planner consumes
normalized `SourceEvent`s (produced by `runtime.ingest`) and immutable
`RuleSnapshot`s (published by the control plane), and emits one `DeliveryPlan`
per route. Payloads are referenced, never embedded.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class EventKind(enum.Enum):
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"


class CloneMode(enum.Enum):
    COPY = "copy"
    FORWARD = "forward"


class ApprovalPolicy(enum.Enum):
    RULE_AUTHORIZED = "rule_authorized"  # clone rules pre-authorize sends
    MESSAGE_REVIEW = "message_review"    # per-message human approval


@dataclass(frozen=True)
class SourceEvent:
    """One normalized inbound event bound to a single receiving account's view.

    `source_scope` namespaces message ids (§6.2): channel/supergroup peers share a
    canonical scope; small-group events must embed the receiving account identity.
    """

    kind: EventKind
    source_scope: str
    source_chat_id: int
    source_message_id: int
    revision: int
    account_id: str
    grouped_id: int | None = None
    payload_ref: str | None = None      # opaque ref to stored content snapshot
    payload_hash: str | None = None     # content fingerprint of this revision
    reply_to_source_id: int | None = None
    topic_id: int | None = None
    protected: bool = False             # source flagged no-save/no-forward
    sender_id: int | None = None        # TG author id; None on deletes/anonymous service posts
    media_kind: str | None = None       # photo/video/document/voice/audio/sticker/gif/poll/text/...


@dataclass(frozen=True)
class RouteTarget:
    route_id: str
    target_chat_id: int
    target_topic_id: int | None = None


@dataclass(frozen=True)
class RuleSnapshot:
    """Immutable published rule version. Runtime never mutates it (§7.5)."""

    rule_id: str
    version: int
    account_id: str
    source_scope: str
    source_chat_id: int
    source_topic_id: int | None
    targets: tuple[RouteTarget, ...]
    mode: CloneMode
    sync_edit: bool
    sync_delete: bool
    approval_policy: ApprovalPolicy = ApprovalPolicy.RULE_AUTHORIZED
    filters: tuple[dict[str, Any], ...] = ()  # e.g. {"sender_user_ids": [..], "media_kinds": [..]} per target


class PlanKind(enum.Enum):
    SEND = "send"
    EDIT = "edit"
    DELETE = "delete"
    TOMBSTONE = "tombstone"  # delete arrived before send; cancel unsent work


@dataclass(frozen=True)
class DeliveryPlan:
    """One planned action for one route. Executor handles exactly one plan (§4.3)."""

    kind: PlanKind
    rule_id: str
    rule_version: int
    route_id: str
    account_id: str
    source_scope: str
    source_chat_id: int
    source_message_id: int
    revision: int
    target_chat_id: int
    target_topic_id: int | None
    mode: CloneMode
    payload_ref: str | None
    payload_hash: str | None
    requires_approval: bool
    reply_to_target_message_id: int | None = None
    grouped_id: int | None = None

    @property
    def idempotency_key(self) -> str:
        return (
            f"{self.rule_id}:{self.route_id}:{self.source_scope}:"
            f"{self.source_chat_id}:{self.source_message_id}:{self.revision}:{self.kind.value}"
        )

"""Album aggregation (§7.3): group same-account/same-chat grouped_id members
within a window; emit a frozen ordered member list. Late members are flagged
visible anomalies — never silently dropped, never re-sent as standalone."""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class MemberDisposition(enum.Enum):
    IN_GROUP = "in_group"
    LATE = "late"  # arrived after the group's window closed


@dataclass(frozen=True)
class AlbumMember:
    message_id: int
    position: int


@dataclass
class AlbumGroup:
    """Aggregation state for one (account, chat, grouped_id)."""

    key: tuple[str, int, int]
    first_seen: float
    members: list[int] = field(default_factory=list)
    closed: bool = False


class AlbumAggregator:
    """Window-based album collector. Clock is injectable for tests."""

    def __init__(self, window_s: float = 1.0, now=time.monotonic):
        self.window_s = window_s
        self._now = now
        self._open: dict[tuple[str, int, int], AlbumGroup] = {}
        self._closed_keys: set[tuple[str, int, int]] = set()

    def add(
        self, account_id: str, chat_id: int, grouped_id: int, message_id: int,
    ) -> tuple[AlbumGroup | None, MemberDisposition]:
        """Returns (closed_group, IN_GROUP) when this add closes a group, or
        (None, LATE) when the member arrived after its group already closed."""
        key = (account_id, chat_id, grouped_id)
        if key in self._closed_keys:
            return None, MemberDisposition.LATE
        group = self._open.get(key)
        if group is None:
            group = AlbumGroup(key=key, first_seen=self._now())
            self._open[key] = group
        if message_id not in group.members:
            group.members.append(message_id)
        closed = self._maybe_close(group)
        return (closed, MemberDisposition.IN_GROUP) if closed else (None, MemberDisposition.IN_GROUP)

    def flush(self) -> list[AlbumGroup]:
        """Close every group whose window elapsed; returns them in close order."""
        closed = []
        for key, group in list(self._open.items()):
            done = self._maybe_close(group)
            if done:
                closed.append(done)
        return closed

    def _maybe_close(self, group: AlbumGroup) -> AlbumGroup | None:
        if self._now() - group.first_seen >= self.window_s:
            group.members.sort()
            group.closed = True
            del self._open[group.key]
            self._closed_keys.add(group.key)
            return group
        return None

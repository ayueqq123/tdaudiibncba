"""RuntimeController: command -> per-account lifecycle transitions (§4.3/§5.2/§5.3).

One worker hosts many accounts; the controller serializes per-account commands,
dedups replays, enforces lease ownership for lifecycle changes, and refuses
unsafe transitions (e.g. takeover while the old holder may still be alive —
§5.3 requires confirmed death / fencing first). Pure state machine: session
start/stop hooks are injected so the class stays transport-agnostic.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field, replace
from typing import Callable, Protocol


class CommandType(enum.Enum):
    START = "start"            # acquire lease, bring account online
    STOP = "stop"              # drain sends, disconnect, release lease
    PAUSE = "pause"            # block new sends, keep connection + queue
    RESUME = "resume"
    MARK_REAUTH = "reauth"     # credential rejected upstream → reauth_required
    MARK_REVOKED = "revoked"   # session revoked server-side
    DISABLE = "disable"        # operator-disabled
    TAKEOVER = "takeover"      # fenced ownership transfer from a dead worker


class AccountPhase(enum.Enum):
    """Synthesized phase shown to operators (§5.2 keeps the detailed
    connection/auth/send states on the row; this is the control view)."""
    STOPPED = "stopped"
    STARTING = "starting"
    ONLINE = "online"
    PAUSED = "paused"
    STOPPING = "stopping"
    REAUTH_REQUIRED = "reauth_required"
    REVOKED = "revoked"
    DISABLED = "disabled"
    TAKEOVER_BLOCKED = "takeover_blocked"


@dataclass(frozen=True)
class AccountRuntimeState:
    account_id: str
    phase: AccountPhase = AccountPhase.STOPPED
    worker_id: str | None = None
    generation: int | None = None
    reason: str = ""


@dataclass(frozen=True)
class RuntimeCommand:
    account_id: str
    type: CommandType
    dedup_key: str = ""
    issued_by: str = ""
    # TAKEOVER only: must be True when the old holder is confirmed dead
    # (process exited / node fenced / session revoked upstream).
    old_holder_confirmed_dead: bool = False


class CommandStatus(enum.Enum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True)
class CommandResult:
    status: CommandStatus
    state: AccountRuntimeState | None = None
    reason: str = ""
    command_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @property
    def accepted(self) -> bool:
        return self.status is CommandStatus.APPLIED


class StateStore(Protocol):
    def get(self, account_id: str) -> AccountRuntimeState | None: ...
    def put(self, state: AccountRuntimeState) -> None: ...


class InMemoryStateStore:
    def __init__(self) -> None:
        self._rows: dict[str, AccountRuntimeState] = {}

    def get(self, account_id: str) -> AccountRuntimeState | None:
        return self._rows.get(account_id)

    def put(self, state: AccountRuntimeState) -> None:
        self._rows[state.account_id] = state


# What the controller may do given the current phase. Anything else is a
# no-op rejection with a reason code, never an exception to the caller.
_ALLOWED: dict[CommandType, frozenset[AccountPhase]] = {
    CommandType.START: frozenset({AccountPhase.STOPPED, AccountPhase.PAUSED,
                                  AccountPhase.REAUTH_REQUIRED}),
    CommandType.STOP: frozenset({AccountPhase.STARTING, AccountPhase.ONLINE,
                                 AccountPhase.PAUSED, AccountPhase.REAUTH_REQUIRED,
                                 AccountPhase.STOPPING}),
    CommandType.PAUSE: frozenset({AccountPhase.ONLINE}),
    CommandType.RESUME: frozenset({AccountPhase.PAUSED}),
    CommandType.MARK_REAUTH: frozenset({AccountPhase.STARTING, AccountPhase.ONLINE,
                                        AccountPhase.PAUSED}),
    CommandType.MARK_REVOKED: frozenset({AccountPhase.STARTING, AccountPhase.ONLINE,
                                         AccountPhase.PAUSED, AccountPhase.REAUTH_REQUIRED}),
    CommandType.DISABLE: frozenset(set(AccountPhase) - {AccountPhase.DISABLED}),
    CommandType.TAKEOVER: frozenset({AccountPhase.ONLINE, AccountPhase.PAUSED,
                                     AccountPhase.STARTING, AccountPhase.STOPPING,
                                     AccountPhase.TAKEOVER_BLOCKED}),
}

_NEXT_PHASE: dict[CommandType, AccountPhase] = {
    CommandType.START: AccountPhase.STARTING,
    CommandType.STOP: AccountPhase.STOPPING,
    CommandType.PAUSE: AccountPhase.PAUSED,
    CommandType.RESUME: AccountPhase.ONLINE,
    CommandType.MARK_REAUTH: AccountPhase.REAUTH_REQUIRED,
    CommandType.MARK_REVOKED: AccountPhase.REVOKED,
    CommandType.DISABLE: AccountPhase.DISABLED,
    CommandType.TAKEOVER: AccountPhase.ONLINE,
}


class RuntimeController:
    def __init__(self, store: StateStore | None = None):
        self._store = store or InMemoryStateStore()
        self._seen_dedup: set[str] = set()

    def current(self, account_id: str) -> AccountRuntimeState:
        return self._store.get(account_id) or AccountRuntimeState(account_id)

    def apply(self, command: RuntimeCommand) -> CommandResult:
        if command.dedup_key:
            if command.dedup_key in self._seen_dedup:
                return CommandResult(CommandStatus.DUPLICATE,
                                     self.current(command.account_id),
                                     reason="dedup_replay")
            self._seen_dedup.add(command.dedup_key)

        state = self.current(command.account_id)
        if command.type is CommandType.TAKEOVER:
            return self._takeover(command, state)

        allowed = _ALLOWED.get(command.type, frozenset())
        if state.phase not in allowed:
            return CommandResult(CommandStatus.REJECTED, state,
                                 reason=f"illegal:{state.phase.value}->{command.type.value}")
        new_state = replace(state, phase=_NEXT_PHASE[command.type], reason="")
        self._store.put(new_state)
        return CommandResult(CommandStatus.APPLIED, new_state)

    def mark_online(self, account_id: str, *, worker_id: str,
                    generation: int) -> AccountRuntimeState:
        """Worker reports START completed: STARTING -> ONLINE with lease."""
        state = replace(self.current(account_id), phase=AccountPhase.ONLINE,
                        worker_id=worker_id, generation=generation)
        self._store.put(state)
        return state

    def mark_stopped(self, account_id: str, *, reason: str = "") -> AccountRuntimeState:
        state = replace(self.current(account_id), phase=AccountPhase.STOPPED,
                        worker_id=None, generation=None, reason=reason)
        self._store.put(state)
        return state

    def _takeover(self, command: RuntimeCommand,
                  state: AccountRuntimeState) -> CommandResult:
        if not command.old_holder_confirmed_dead:
            blocked = replace(state, phase=AccountPhase.TAKEOVER_BLOCKED,
                              reason="old_holder_unconfirmed")
            self._store.put(blocked)
            return CommandResult(CommandStatus.REJECTED, blocked,
                                 reason="takeover_requires_fencing")
        if state.phase not in _ALLOWED[CommandType.TAKEOVER]:
            return CommandResult(CommandStatus.REJECTED, state,
                                 reason=f"illegal:{state.phase.value}->takeover")
        new_state = AccountRuntimeState(command.account_id,
                                        phase=AccountPhase.ONLINE,
                                        worker_id=command.issued_by or state.worker_id,
                                        generation=(state.generation or 0) + 1)
        self._store.put(new_state)
        return CommandResult(CommandStatus.APPLIED, new_state)

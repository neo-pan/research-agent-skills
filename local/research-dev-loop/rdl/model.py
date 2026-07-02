"""Shared RDL vocabulary for Python modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StrEnum(str, Enum):
    """String-valued enum compatible with older Python versions."""

    def __str__(self) -> str:
        return self.value


class SessionMode(StrEnum):
    RESEARCH = "research"
    BUILD = "build"


class SessionPhase(StrEnum):
    PLAN = "plan"
    WORK = "work"
    EVIDENCE = "evidence"
    INTERPRET = "interpret"
    REVIEW = "review"
    DECIDE = "decide"
    COMPLETE = "complete"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    CLOSED_POSITIVE = "closed-positive"
    CLOSED_NEGATIVE = "closed-negative"
    CLOSED_INCONCLUSIVE = "closed-inconclusive"
    ABANDONED = "abandoned"


class DecisionType(StrEnum):
    CONTINUE = "continue"
    PIVOT = "pivot"
    NARROW = "narrow"
    BROADEN = "broaden"
    DIAGNOSE = "diagnose"
    BUILD = "build"
    PROFILE = "profile"
    RERUN = "rerun"
    ACCEPT = "accept"
    REJECT = "reject"
    CLOSE_POSITIVE = "close-positive"
    CLOSE_NEGATIVE = "close-negative"
    CLOSE_INCONCLUSIVE = "close-inconclusive"


class CloseOutcome(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class Blocker:
    code: str
    file: str
    message: str
    next_action: str


@dataclass(frozen=True)
class CommandResult:
    status: str
    action: str
    session_id: str = ""
    mode: str = ""
    phase: str = ""
    round: int = 0
    missing: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    blockers: tuple[Blocker, ...] = field(default_factory=tuple)
    next_action: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionState:
    schema_version: int
    session_id: str
    mode: SessionMode
    phase: SessionPhase
    round: int
    status: SessionStatus
    mission_file: str
    guard_session_id: str | None = None
    last_guard_command_id: str | None = None
    prompt_objective: str = ""
    created_at_utc: str = ""
    updated_at_utc: str = ""

    @classmethod
    def from_json(cls, data: Any) -> "SessionState":
        if not isinstance(data, dict):
            raise ValueError("state.json must contain a JSON object")
        return cls(
            schema_version=_int_field(data, "schema_version"),
            session_id=_str_field(data, "session_id"),
            mode=SessionMode(_str_field(data, "mode")),
            phase=SessionPhase(_str_field(data, "phase")),
            round=_int_field(data, "round"),
            status=SessionStatus(_str_field(data, "status")),
            mission_file=_str_field(data, "mission_file"),
            guard_session_id=_optional_str_field(data, "guard_session_id"),
            last_guard_command_id=_optional_str_field(data, "last_guard_command_id"),
            prompt_objective=_optional_str_field(data, "prompt_objective") or "",
            created_at_utc=_optional_str_field(data, "created_at_utc") or "",
            updated_at_utc=_optional_str_field(data, "updated_at_utc") or "",
        )


@dataclass(frozen=True)
class AuditResult:
    errors: tuple[Blocker, ...] = ()
    blockers: tuple[Blocker, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors and not self.blockers


def _str_field(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _optional_str_field(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    return value if isinstance(value, str) else ""


def _int_field(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool):
        return 0
    return value if isinstance(value, int) else 0

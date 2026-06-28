"""Shared RDL vocabulary for Python modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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

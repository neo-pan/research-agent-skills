"""Conservative repair planning and execution for RDL sessions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import integrity, safety, templates
from .model import Blocker
from .session import Session, SessionLockError, acquire_session_lock


@dataclass(frozen=True)
class RepairResult:
    repaired: tuple[str, ...]
    errors: tuple[Blocker, ...]
    blockers: tuple[Blocker, ...]

    @property
    def ok(self) -> bool:
        return not self.errors and not self.blockers


def repair(session: Session) -> RepairResult:
    repaired: list[str] = []
    blockers: list[Blocker] = []

    _repair_stale_lock(session.root / ".lock", repaired, blockers)
    if blockers:
        return RepairResult(tuple(repaired), (), tuple(blockers))

    try:
        with acquire_session_lock(session, "repair"):
            assessment = safety.assess_repair_scope(session)
            if assessment.errors or assessment.blockers:
                return RepairResult(tuple(repaired), assessment.errors, assessment.blockers)

            prompt_blockers = _repair_initial_prompt(session, repaired)
            if prompt_blockers:
                return RepairResult(tuple(repaired), (), tuple(prompt_blockers))

            integrity.refresh(session)
            repaired.append("integrity.json")
    except SessionLockError as exc:
        return RepairResult(tuple(repaired), (), (exc.blocker,))
    return RepairResult(tuple(repaired), (), ())


def _repair_stale_lock(path: Path, repaired: list[str], blockers: list[Blocker]) -> None:
    if not path.is_file():
        return
    blocker = safety.repair_lock_blocker(path)
    if blocker is None:
        return
    if blocker.code == "session_locked":
        blockers.append(
            Blocker(
                "session_locked",
                ".lock",
                "RDL session lock is held by another running process.",
                "Wait for the current RDL command to finish.",
            )
        )
        return
    if blocker.code != "stale_lock":
        blockers.append(blocker)
        return
    path.unlink()
    repaired.append(".lock")


def _repair_initial_prompt(session: Session, repaired: list[str]) -> list[Blocker]:
    prompt_relative = f"rounds/{session.state.round:03d}/prompt.md"
    prompt_path = session.root / prompt_relative
    if prompt_path.is_file():
        return []
    if session.state.round != 1:
        return [
            Blocker(
                "unsafe_missing_prompt",
                prompt_relative,
                "Only the initial round prompt can be deterministically repaired.",
                f"Restore {prompt_relative} from a known-good source.",
            )
        ]
    if not session.state.prompt_objective:
        return [
            Blocker(
                "missing_prompt_metadata",
                prompt_relative,
                "Initial prompt cannot be deterministically repaired without prompt_objective metadata.",
                f"Restore {prompt_relative} or start a new session with prompt metadata.",
            )
        ]
    templates.write_prompt(prompt_path, session.state.mode, session.state.profile, 1, session.state.prompt_objective, "none")
    repaired.append(prompt_relative)
    return []

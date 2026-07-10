"""Conservative repair planning and execution for RDL sessions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import documents, integrity, safety, store, templates
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

            review_blockers = _repair_review_sections(session, repaired)
            if review_blockers:
                return RepairResult(tuple(repaired), (), tuple(review_blockers))

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


def _repair_review_sections(session: Session, repaired: list[str]) -> list[Blocker]:
    rounds_dir = session.root / "rounds"
    if not rounds_dir.is_dir():
        return []

    blockers: list[Blocker] = []
    for review_path in sorted(rounds_dir.glob("[0-9][0-9][0-9]/review.md")):
        review_blockers = documents.validate("review", review_path)
        if not review_blockers:
            continue
        if not _only_missing_repairable_review_sections(review_blockers):
            blockers.extend(review_blockers)
            continue
        repaired_sections = _append_missing_review_sections(review_path)
        if repaired_sections:
            repaired.append(str(review_path.relative_to(session.root)))
    return blockers


def _only_missing_repairable_review_sections(blockers: list[Blocker]) -> bool:
    allowed_locations = {
        "Returned Review Findings",
        "Accepted Corrections and Resolutions",
    }
    for blocker in blockers:
        if blocker.code != "missing_review_section":
            return False
        if not any(str(blocker.file).endswith(f"#{heading}") for heading in allowed_locations):
            return False
    return True


def _append_missing_review_sections(path: Path) -> list[str]:
    text = store.read_text(path).rstrip()
    additions: list[tuple[str, str]] = []
    if documents.section(path, "Returned Review Findings").start_line is None:
        additions.append(("Returned Review Findings", "none"))
    if documents.section(path, "Accepted Corrections and Resolutions").start_line is None:
        additions.append(("Accepted Corrections and Resolutions", "none recorded"))
    if not additions:
        return []

    chunks = [text]
    for heading, content in additions:
        chunks.append(f"## {heading}\n\n{content}")
    store.write_text_atomic(path, "\n\n".join(chunks).rstrip() + "\n")
    return [heading for heading, _content in additions]

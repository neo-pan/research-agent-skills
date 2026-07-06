"""Clean-context review packs for RDL semantic review adapters."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import documents, memory, store
from .session import Session


PRIOR_ROUND_WINDOW = 2

ROUND_RECORDS = (
    "prompt.md",
    "intent.md",
    "work.md",
    "evidence.md",
    "interpretation.md",
    "review.md",
    "decision.md",
    "events.md",
)

SESSION_RECORDS = (
    "mission.md",
    "progress.md",
    "factors.md",
    "decision-ledger.md",
    "artifact-manifest.json",
)

PRIOR_ROUND_RECORDS = (
    "evidence.md",
    "interpretation.md",
    "review.md",
    "decision.md",
    "events.md",
)


@dataclass(frozen=True)
class ReviewPack:
    session_id: str
    action: str
    round: int
    mode: str
    profile: str
    reviewer_task: dict[str, Any]
    finding_schema: dict[str, Any]
    agent_review_signals: tuple[dict[str, str], ...]
    records: tuple[dict[str, str], ...]
    artifact_manifest: dict[str, Any] | None
    deterministic_findings: tuple[dict[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "action": self.action,
            "round": self.round,
            "mode": self.mode,
            "profile": self.profile,
            "reviewer_task": self.reviewer_task,
            "finding_schema": self.finding_schema,
            "agent_review_signals": list(self.agent_review_signals),
            "records": list(self.records),
            "artifact_manifest": self.artifact_manifest,
            "deterministic_findings": list(self.deterministic_findings),
        }

    def summary(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "action": self.action,
            "round": self.round,
            "mode": self.mode,
            "profile": self.profile,
            "agent_review_signal_codes": [signal["code"] for signal in self.agent_review_signals],
            "record_paths": [record["path"] for record in self.records],
            "artifact_count": _artifact_count(self.artifact_manifest),
            "deterministic_finding_codes": [finding["code"] for finding in self.deterministic_findings],
        }


def build(session: Session, action: str, deterministic_gate_report: Any) -> ReviewPack:
    """Build a clean RDL-only context pack for semantic review adapters."""

    records = []
    for relative in _record_paths(session):
        path = session.root / relative
        if path.is_file():
            records.append(_record(path, relative))
    return ReviewPack(
        session_id=session.state.session_id,
        action=action,
        round=session.state.round,
        mode=str(session.state.mode),
        profile=str(session.state.profile),
        reviewer_task=_reviewer_task(),
        finding_schema=_finding_schema(),
        agent_review_signals=memory.agent_review_signals(session),
        records=tuple(records),
        artifact_manifest=_artifact_manifest(session.root / "artifact-manifest.json"),
        deterministic_findings=tuple(
            finding
            for finding in deterministic_gate_report.details.get("findings", [])
            if finding.get("category") != "semantic"
        ),
    )


def _reviewer_task() -> dict[str, Any]:
    return {
        "role": "independent semantic reviewer",
        "instructions": [
            "Use only the supplied RDL records, artifact manifest facts, deterministic findings, and cited evidence.",
            "Do not rely on main-agent conversation history.",
            "Do not edit canonical RDL files or advance the session.",
            "Return structured findings for the main agent or user to record in review.md.",
        ],
        "questions": [
            "Does the evidence support the claim or capability decision?",
            "Are there overclaim risks or missing decision-grade evidence?",
            "Is the current direction becoming stale or repeating without useful fresh evidence?",
            "Does top-level session memory faithfully preserve handoff state?",
            "Do active items, blockers, deferred items, and open questions still represent the true state?",
        ],
    }


def _finding_schema() -> dict[str, Any]:
    return {
        "required_fields": ["severity", "category", "location", "claim", "required_resolution", "source"],
        "severity": ["blocking", "warning", "note"],
        "category": ["evidence", "overclaim", "staleness", "handoff", "memory", "artifact", "decision"],
        "source": ["manual", "checklist", "phase-review", "subagent", "project-adapter"],
    }


def _record_paths(session: Session) -> tuple[str, ...]:
    paths = []
    mission_file = str(session.state.mission_file)
    if mission_file:
        paths.append(mission_file)
    paths.extend(path for path in SESSION_RECORDS if path != "mission.md")
    round_prefix = f"rounds/{session.state.round:03d}"
    paths.extend(f"{round_prefix}/{name}" for name in ROUND_RECORDS)
    for round_number in _prior_completed_rounds(session, limit=PRIOR_ROUND_WINDOW):
        prior_round_prefix = f"rounds/{round_number:03d}"
        paths.extend(f"{prior_round_prefix}/{name}" for name in PRIOR_ROUND_RECORDS)
    return tuple(dict.fromkeys(paths))


def _prior_completed_rounds(session: Session, *, limit: int) -> tuple[int, ...]:
    rounds = []
    for round_number in range(session.state.round - 1, 0, -1):
        if _round_completed(session.round_dir(round_number)):
            rounds.append(round_number)
        if len(rounds) == limit:
            break
    return tuple(reversed(rounds))


def _round_completed(round_dir: Path) -> bool:
    decision = documents.field(round_dir / "decision.md", "Decision")
    return _meaningful(decision)


def _record(path: Path, relative: str) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    return {
        "path": relative,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text": text,
    }


def _artifact_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = store.read_json(path)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _artifact_count(manifest: dict[str, Any] | None) -> int:
    if not manifest:
        return 0
    artifacts = manifest.get("artifacts")
    return len(artifacts) if isinstance(artifacts, list) else 0


def _meaningful(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(normalized and normalized not in {"-", "...", "tbd", "todo", "n/a", "not applicable", "none recorded"})

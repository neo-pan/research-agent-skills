"""Clean-context review packs for RDL semantic review adapters."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import store
from .session import Session


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


@dataclass(frozen=True)
class ReviewPack:
    session_id: str
    action: str
    round: int
    mode: str
    profile: str
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
        records=tuple(records),
        artifact_manifest=_artifact_manifest(session.root / "artifact-manifest.json"),
        deterministic_findings=tuple(
            finding
            for finding in deterministic_gate_report.details.get("findings", [])
            if finding.get("category") != "semantic"
        ),
    )


def _record_paths(session: Session) -> tuple[str, ...]:
    paths = []
    mission_file = str(session.state.mission_file)
    if mission_file:
        paths.append(mission_file)
    paths.extend(path for path in SESSION_RECORDS if path != "mission.md")
    round_prefix = f"rounds/{session.state.round:03d}"
    paths.extend(f"{round_prefix}/{name}" for name in ROUND_RECORDS)
    return tuple(dict.fromkeys(paths))


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

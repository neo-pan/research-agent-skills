"""Clean-context review packs for RDL semantic review adapters."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import documents, memory, store, summary, transition
from .session import Session


PRIOR_ROUND_WINDOW = 2
SUBJECT_DIGEST_VERSION = 1
SUPPORTED_SUBJECT_ACTIONS = frozenset({"review", "doctor", "next", "close"})

EXPECTED_REVIEW_ABSENCE_CODES = {
    "missing_review",
    "missing_semantic_review",
}

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
    "final-report.md",
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
    subject_digest: str
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
            "subject_digest": self.subject_digest,
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
            "subject_digest": self.subject_digest,
            "agent_review_signal_codes": [signal["code"] for signal in self.agent_review_signals],
            "record_paths": [record["path"] for record in self.records],
            "artifact_count": _artifact_count(self.artifact_manifest),
            "deterministic_finding_codes": [finding["code"] for finding in self.deterministic_findings],
        }


def build(session: Session, action: str, deterministic_gate_report: Any) -> ReviewPack:
    """Build a clean RDL-only context pack for semantic review adapters."""

    normalized_action = _normalize_action(action)
    records = []
    for relative in _record_paths(session):
        path = session.root / relative
        if path.is_file():
            records.append(_record(path, relative))
    agent_review_signals = memory.agent_review_signals(session)
    artifact_manifest = _artifact_manifest(session.root / "artifact-manifest.json")
    deterministic_findings = tuple(
        finding
        for finding in deterministic_gate_report.details.get("findings", [])
        if _include_deterministic_finding(finding)
    )
    subject_digest = _subject_digest(
        session,
        normalized_action,
        tuple(records),
        artifact_manifest,
        deterministic_findings,
        agent_review_signals,
    )
    return ReviewPack(
        session_id=session.state.session_id,
        action=normalized_action,
        round=session.state.round,
        mode=str(session.state.mode),
        profile=str(session.state.profile),
        subject_digest=subject_digest,
        reviewer_task=_reviewer_task(normalized_action, str(session.state.mode), str(session.state.profile)),
        finding_schema=_finding_schema(),
        agent_review_signals=agent_review_signals,
        records=tuple(records),
        artifact_manifest=artifact_manifest,
        deterministic_findings=deterministic_findings,
    )


def _normalize_action(action: str) -> str:
    return "next" if action == "advance" else action


def _include_deterministic_finding(finding: dict[str, Any]) -> bool:
    return finding.get("category") != "semantic" and finding.get("code") not in EXPECTED_REVIEW_ABSENCE_CODES


def _reviewer_task(action: str, mode: str, profile: str) -> dict[str, Any]:
    questions = [
        "Does the supplied evidence support the proposed claim or capability decision?",
        "Are there overclaim risks, missing decision-grade evidence, or unresolved confounders?",
        "Is the current direction stale, repeating, or missing a concrete stall response?",
        "Does top-level session memory faithfully preserve active, blocked, deferred, and open-question state?",
    ]
    if action == "close":
        questions.append(
            "Is the close outcome scoped correctly, with remaining unknowns and next-loop uncertainty preserved, "
            "and will session memory remain faithful after the proposed close?"
        )
    elif action == "next":
        questions.append("Is there enough fresh evidence and a concrete next smallest step to advance the round?")
    if mode == "build":
        questions.append("Are work artifacts and verification evidence sufficient for the capability decision?")
    elif mode == "research":
        questions.append("Are claim, uncertainty, and what-remains-unknown separated clearly?")
    if profile == "full-review":
        questions.append("Would any finding require revise-before-close, block, or inconclusive rather than pass?")

    return {
        "role": "independent semantic reviewer",
        "mode": mode,
        "profile": profile,
        "action": action,
        "instructions": [
            "Use only the supplied RDL records, artifact manifest facts, deterministic findings, and cited evidence.",
            "Do not rely on main-agent conversation history.",
            "Do not edit canonical RDL files or advance the session.",
            "Return a compact verdict recommendation plus structured findings for review.md.",
        ],
        "output": {
            "subject_action": "echo review_pack.action exactly",
            "subject_digest": "echo review_pack.subject_digest exactly",
            "verdict_recommendation": "pass | revise-before-close | block | inconclusive",
            "memory_fidelity": "faithful | needs-correction | incomplete",
            "next_action_recommendation": "close | next | revise | stop",
            "finding_line_format": "- severity | category | location | claim | required_resolution",
        },
        "questions": questions,
    }


def _finding_schema() -> dict[str, Any]:
    return {
        "required_fields": ["severity", "category", "location", "claim", "required_resolution"],
        "severity": ["blocking", "warning", "note"],
        "category": ["evidence", "overclaim", "staleness", "handoff", "memory", "artifact", "decision"],
        "line_format": "- severity | category | location | claim | required_resolution",
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
    for round_number in _cited_artifact_rounds(session):
        cited_round_prefix = f"rounds/{round_number:03d}"
        paths.extend(f"{cited_round_prefix}/{name}" for name in PRIOR_ROUND_RECORDS)
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


def _cited_artifact_rounds(session: Session) -> tuple[int, ...]:
    manifest = _artifact_manifest(session.root / "artifact-manifest.json")
    if not manifest:
        return ()
    artifact_ids = _current_cited_artifact_ids(session)
    if not artifact_ids:
        return ()
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        return ()

    rounds = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("id") not in artifact_ids:
            continue
        round_number = artifact.get("round")
        if isinstance(round_number, int) and not isinstance(round_number, bool) and 1 <= round_number < session.state.round:
            rounds.add(round_number)
    return tuple(sorted(rounds))


def _current_cited_artifact_ids(session: Session) -> set[str]:
    artifact_ids: set[str] = set()
    for path in _current_citation_sources(session):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        artifact_ids.update(documents.extract_artifact_ids(text))
        if path.name == "evidence.md":
            artifact_ids.update(_evidence_artifact_table_ids(documents.section(path, "Evidence Artifacts").content))
    return artifact_ids


def _current_citation_sources(session: Session) -> tuple[Path, ...]:
    round_dir = session.round_dir()
    return (
        round_dir / "decision.md",
        round_dir / "evidence.md",
        session.root / "final-report.md",
    )


def _evidence_artifact_table_ids(markdown: str) -> set[str]:
    artifact_ids: set[str] = set()
    for row in _table_rows(markdown):
        artifact_id = row.get("id", "")
        if _meaningful(artifact_id):
            artifact_ids.add(artifact_id)
    return artifact_ids


def _table_rows(markdown: str) -> list[dict[str, str]]:
    rows = [line.strip() for line in markdown.splitlines() if line.strip().startswith("|") and line.strip().endswith("|")]
    if not rows:
        return []
    header = _table_cells(rows[0])
    result: list[dict[str, str]] = []
    for row in rows[1:]:
        if _table_separator(row):
            continue
        cells = _table_cells(row)
        result.append({header[index].strip().lower(): cells[index].strip() if index < len(cells) else "" for index in range(len(header))})
    return result


def _table_cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _table_separator(row: str) -> bool:
    return all(character in "| :-\t" for character in row.strip())


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


def _subject_digest(
    session: Session,
    action: str,
    records: tuple[dict[str, str], ...],
    artifact_manifest: dict[str, Any] | None,
    deterministic_findings: tuple[dict[str, str], ...],
    agent_review_signals: tuple[dict[str, str], ...],
) -> str:
    current_review = f"rounds/{session.state.round:03d}/review.md"
    subject_records = []
    for record in records:
        relative = record["path"]
        if relative in {current_review, "artifact-manifest.json"}:
            continue
        text = summary.without_generated_blocks(relative, record["text"])
        if relative == "decision-ledger.md":
            text = transition.without_generated_close_record(session, text)
        subject_records.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )

    stable_findings = tuple(
        finding for finding in deterministic_findings if finding.get("category") in {"artifact", "evidence"}
    )
    payload = {
        "version": SUBJECT_DIGEST_VERSION,
        "session_id": session.state.session_id,
        "round": session.state.round,
        "mode": str(session.state.mode),
        "profile": str(session.state.profile),
        "action": action,
        "records": sorted(subject_records, key=lambda record: record["path"]),
        "artifact_manifest_sha256": _canonical_digest(artifact_manifest),
        "deterministic_findings": _canonical_items(stable_findings),
        "agent_review_signals": _canonical_items(agent_review_signals),
    }
    return _canonical_digest(payload)


def _canonical_items(items) -> list[Any]:
    normalized = [json.loads(_canonical_json(item)) for item in items]
    return sorted(normalized, key=_canonical_json)


def _canonical_digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(value).encode('utf-8')).hexdigest()}"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _meaningful(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(normalized and normalized not in {"-", "...", "tbd", "todo", "n/a", "not applicable", "none recorded"})

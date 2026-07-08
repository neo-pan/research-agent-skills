"""Readiness rule execution for RDL transitions and doctor checks."""

from __future__ import annotations

import re
from pathlib import Path

from . import documents, store
from .model import Blocker, RoundProfile, SessionMode
from .protocol import descriptor
from .session import Session


def check(session: Session, plan: str, outcome: str | None = None) -> list[Blocker]:
    rules = descriptor.readiness_plan(plan)
    if not rules:
        return [
            Blocker(
                "invalid_readiness_plan",
                plan,
                "Internal readiness plan is unsupported.",
                "Fix the RDL readiness descriptor.",
            )
        ]

    blockers: list[Blocker] = []
    for rule in rules:
        blockers.extend(_apply_rule(session, rule, outcome))
    return blockers


def _apply_rule(session: Session, rule: str, outcome: str | None) -> list[Blocker]:
    round_dir = session.round_dir()
    expected_closes = descriptor.expected_closes(session.state.mode)
    profile = session.state.profile

    if rule == "review":
        return _validate_profile_review(profile, round_dir)
    if rule == "decision":
        return documents.validate("decision", round_dir / "decision.md", {"expected_closes": expected_closes})
    if rule == "mode-minimums":
        return _validate_profile_round_minimums(session.state.mode, profile, round_dir)
    if rule == "round-evidence-discipline":
        return _validate_round_evidence_discipline(round_dir)
    if rule == "artifact-citations":
        return _validate_artifact_citations(session.root, round_dir)
    if rule == "full-review-close-profile":
        if profile != RoundProfile.FULL_REVIEW:
            return [_close_requires_full_review_blocker(round_dir / "decision.md")]
        return []
    if rule == "final-report":
        return documents.validate("final-report", session.root / "final-report.md", {"outcome": outcome})
    if rule == "close-evidence-discipline":
        return _validate_close_evidence_discipline(round_dir)
    if rule == "progress-close-readiness":
        return _validate_progress_close_readiness(session.root, outcome)
    if rule == "close-if-decision":
        decision = documents.field(round_dir / "decision.md", "Decision")
        close_outcome = descriptor.close_outcome_for_decision(decision)
        if close_outcome:
            if profile != RoundProfile.FULL_REVIEW:
                return [_close_requires_full_review_blocker(round_dir / "decision.md")]
            return check(session, "close", close_outcome)
        return []
    return [
        Blocker(
            "invalid_readiness_rule",
            rule,
            "Internal readiness rule is unsupported.",
            "Fix the RDL readiness descriptor.",
        )
    ]


def _validate_profile_review(profile: RoundProfile, round_dir: Path) -> list[Blocker]:
    review_file = round_dir / "review.md"
    if profile == RoundProfile.FULL_REVIEW or review_file.is_file():
        return documents.validate("review", review_file)
    return []


def _validate_profile_round_minimums(mode: SessionMode, profile: RoundProfile, round_dir: Path) -> list[Blocker]:
    if profile == RoundProfile.CHECKPOINT:
        return []
    if profile == RoundProfile.BUILD_UPDATE:
        if mode != SessionMode.BUILD:
            return [
                Blocker(
                    "invalid_profile_for_mode",
                    "",
                    "build-update profile is only supported for build mode.",
                    "Use checkpoint or full-review for research mode.",
                )
            ]
        return _validate_build_minimums(round_dir)
    return _validate_mode_round_minimums(mode, round_dir)


def _validate_mode_round_minimums(mode: SessionMode, round_dir: Path) -> list[Blocker]:
    blockers: list[Blocker] = []
    if mode == SessionMode.RESEARCH:
        blockers.extend(
            _validate_round_file_content(
                round_dir,
                "evidence.md",
                "missing_research_evidence",
                "Research rounds require evidence.md with non-placeholder evidence.",
                "Record research evidence before running rdl next.",
            )
        )
        blockers.extend(
            _validate_round_file_content(
                round_dir,
                "interpretation.md",
                "missing_interpretation",
                "Research rounds require interpretation.md with non-placeholder interpretation.",
                "Record interpretation before running rdl next.",
            )
        )
        return blockers

    return _validate_build_minimums(round_dir)


def _validate_build_minimums(round_dir: Path) -> list[Blocker]:
    blockers: list[Blocker] = []
    blockers.extend(
        _validate_round_file_content(
            round_dir,
            "intent.md",
            "missing_build_intent",
            "Build rounds require intent.md with non-placeholder intent.",
            "Record build intent before running rdl next.",
        )
    )
    blockers.extend(
        _validate_round_file_content(
            round_dir,
            "work.md",
            "missing_build_work",
            "Build rounds require work.md with non-placeholder work.",
            "Record build work before running rdl next.",
        )
    )
    blockers.extend(_validate_build_verification_evidence(round_dir))
    return blockers


def _close_requires_full_review_blocker(decision_file: Path) -> Blocker:
    return Blocker(
        "close_requires_full_review_profile",
        f"{decision_file}#Decision",
        "Closing decisions require the full-review profile.",
        "Switch to full-review for the closing round and complete full close readiness.",
    )


def _validate_round_file_content(round_dir: Path, file_name: str, code: str, message: str, next_action: str) -> list[Blocker]:
    path = round_dir / file_name
    if not path.is_file() or not documents.has_content(path):
        return [Blocker(code, str(path), message, next_action)]
    return []


def _validate_build_verification_evidence(round_dir: Path) -> list[Blocker]:
    evidence_file = round_dir / "evidence.md"
    if not evidence_file.is_file():
        return [
            Blocker(
                "missing_verification_evidence",
                str(evidence_file),
                "Build rounds require evidence.md with verification evidence for the capability.",
                "Add verification evidence before running rdl next.",
            )
        ]
    text = store.read_text(evidence_file)
    has_label = any(_verification_evidence_label_has_content(line) for line in text.splitlines())
    if has_label or documents.section_has_content(evidence_file, "Verification Evidence"):
        return []
    return [
        Blocker(
            "missing_verification_evidence",
            str(evidence_file),
            "Build evidence must explicitly identify verification evidence.",
            "Record verification evidence in evidence.md.",
        )
    ]


def _verification_evidence_label_has_content(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped.lower().startswith("verification evidence:"):
        return False
    return any(ch.isalnum() for ch in stripped.split(":", 1)[1])


def _validate_round_evidence_discipline(round_dir: Path) -> list[Blocker]:
    evidence_file = round_dir / "evidence.md"
    if not evidence_file.is_file():
        return [
            Blocker(
                "missing_evidence",
                str(evidence_file),
                "Current round requires evidence.md.",
                "Create evidence.md and record evidence discipline.",
            )
        ]
    blockers: list[Blocker] = []
    for heading, code, message, next_action in (
        ("Missing Evidence", "missing_evidence_discipline", "Missing Evidence must be recorded for the round.", "Record missing evidence or explicitly state none."),
        ("Evaluation Integrity", "missing_evaluation_integrity", "Evaluation Integrity must be recorded for the round.", "Record evaluation integrity notes or an explicit not-applicable note."),
        ("Evidence Budget", "missing_evidence_budget", "Evidence Budget must be recorded for the round.", "Record the evidence budget used or remaining."),
    ):
        if not documents.section_has_content(evidence_file, heading):
            blockers.append(Blocker(code, f"{evidence_file}#{heading}", message, next_action))
    return blockers


def _validate_close_evidence_discipline(round_dir: Path) -> list[Blocker]:
    evidence_file = round_dir / "evidence.md"
    if not evidence_file.is_file():
        return [
            Blocker(
                "missing_close_evidence",
                str(evidence_file),
                "Closing requires current-round evidence.md.",
                "Create evidence.md and record close evidence discipline.",
            )
        ]
    return _validate_round_evidence_discipline(round_dir)


def _validate_progress_close_readiness(session_dir: Path, outcome: str | None) -> list[Blocker]:
    progress_file = session_dir / "progress.md"
    if not progress_file.is_file():
        return []

    blockers: list[Blocker] = []
    if outcome != "inconclusive":
        for row in _table_rows(documents.section(progress_file, "Open Questions").content):
            question = row.get("question", "")
            blocking = row.get("blocking", row.get("blocking?", ""))
            resolution = row.get("resolution", "")
            if _meaningful(question) and blocking.strip().lower() in {"yes", "y", "true", "blocking"} and not _meaningful(resolution):
                blockers.append(
                    Blocker(
                        "unresolved_blocking_open_questions",
                        "progress.md#Open Questions",
                        "Blocking open questions must be resolved before closing positive or negative.",
                        "Resolve blocking open questions or close inconclusive.",
                    )
                )
                break

    for row in _table_rows(documents.section(progress_file, "Deferred").content):
        item = row.get("item", "")
        reason = row.get("reason", "")
        trigger = row.get("revisit trigger", "")
        if _meaningful(item) and (not _meaningful(reason) or not _meaningful(trigger)):
            blockers.append(
                Blocker(
                    "incomplete_deferred_items",
                    "progress.md#Deferred",
                    "Deferred items must include a reason and revisit trigger before closing.",
                    "Complete deferred item reason and revisit trigger.",
                )
            )
            break

    return blockers


def _validate_artifact_citations(session_dir: Path, round_dir: Path) -> list[Blocker]:
    manifest_file = session_dir / "artifact-manifest.json"
    if not manifest_file.is_file():
        return []
    try:
        manifest = store.read_json(manifest_file)
    except Exception:
        return []
    artifacts = manifest.get("artifacts", []) if isinstance(manifest, dict) else []
    manifest_ids = {artifact.get("id") for artifact in artifacts if isinstance(artifact, dict) and artifact.get("id")}
    blockers: list[Blocker] = []

    for path, label, text in _citation_sources(session_dir, round_dir):
        for artifact_id in _artifact_ids_for_source(label, text):
            if artifact_id not in manifest_ids:
                blockers.append(
                    Blocker(
                        "missing_artifact_citation",
                        f"{manifest_file}#{artifact_id}",
                        f"{path}#{label} cites artifact ID {artifact_id}, but artifact-manifest.json has no matching artifact.",
                        f"Add {artifact_id} to artifact-manifest.json or remove the citation.",
                    )
                )
    return blockers


def _artifact_ids_for_source(label: str, text: str) -> set[str]:
    artifact_ids = set(documents.extract_artifact_ids(text))
    if label == "Evidence Artifacts":
        artifact_ids.update(_evidence_artifact_table_ids(text))
    return artifact_ids


def _evidence_artifact_table_ids(markdown: str) -> set[str]:
    artifact_ids: set[str] = set()
    for row in _table_rows(markdown):
        artifact_id = row.get("id", "")
        if _meaningful(artifact_id):
            artifact_ids.add(artifact_id)
    return artifact_ids


def _citation_sources(session_dir: Path, round_dir: Path) -> list[tuple[Path, str, str]]:
    sources: list[tuple[Path, str, str]] = []
    decision_file = round_dir / "decision.md"
    if decision_file.is_file():
        sources.append((decision_file, "Evidence", documents.field_text(decision_file, "Evidence")))
    evidence_file = round_dir / "evidence.md"
    if evidence_file.is_file():
        sources.append((evidence_file, "Evidence Artifacts", documents.section(evidence_file, "Evidence Artifacts").content))
    report_file = session_dir / "final-report.md"
    if report_file.is_file():
        sources.append((report_file, "Evidence Cited", documents.section(report_file, "Evidence Cited").content))
    return sources


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
    return bool(re.fullmatch(r"\|[ \t:|-]+\|[ \t|:-]*", row.strip()))


def _meaningful(value: str) -> bool:
    stripped = value.strip()
    return bool(stripped and stripped.lower() not in {"-", "...", "tbd", "todo", "n/a"} and re.search(r"[A-Za-z0-9]", stripped))

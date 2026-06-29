"""Readiness rule execution for RDL transitions and doctor checks."""

from __future__ import annotations

import re
from pathlib import Path

from . import documents, store
from .model import Blocker, SessionMode
from .protocol import descriptor
from .session import Session


NO_REVIEW_GAP_VALUES = {"none", "no", "no blocking gaps", "no blocking evidence gaps", "n/a", "not applicable", "-", "...", "tbd", "todo"}


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

    if rule == "review":
        return documents.validate("review", round_dir / "review.md")
    if rule == "decision":
        return documents.validate("decision", round_dir / "decision.md", {"expected_closes": expected_closes})
    if rule == "review-decision-alignment":
        return _validate_review_decision_alignment(round_dir)
    if rule == "mode-minimums":
        return _validate_mode_round_minimums(session.state.mode, round_dir)
    if rule == "round-evidence-discipline":
        return _validate_round_evidence_discipline(round_dir)
    if rule == "artifact-citations":
        return _validate_artifact_citations(session.root, round_dir)
    if rule == "final-report":
        return documents.validate("final-report", session.root / "final-report.md", {"outcome": outcome})
    if rule == "close-evidence-discipline":
        return _validate_close_evidence_discipline(round_dir)
    if rule == "progress-close-readiness":
        return _validate_progress_close_readiness(session.root, outcome)
    if rule == "repeated-negative-evidence":
        return _validate_repeated_negative_evidence(session, round_dir)
    if rule == "close-if-decision":
        decision = documents.field(round_dir / "decision.md", "Decision")
        close_outcome = descriptor.close_outcome_for_decision(decision)
        if close_outcome:
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


def _validate_review_decision_alignment(round_dir: Path) -> list[Blocker]:
    review_file = round_dir / "review.md"
    decision_file = round_dir / "decision.md"
    if not review_file.is_file() or not decision_file.is_file():
        return []
    decision = documents.field(decision_file, "Decision")
    review_blockers = _validate_review_not_blocked(review_file, decision)
    if review_blockers:
        return review_blockers
    recommended = documents.field(review_file, "Recommended Decision")
    if recommended and decision and recommended != decision:
        return [
            Blocker(
                "review_decision_mismatch",
                f"{review_file}#Recommended Decision",
                "Review recommended decision does not match decision.md.",
                "Align review.md and decision.md before advancing.",
            )
        ]
    return []


def _validate_review_not_blocked(review_file: Path, decision: str) -> list[Blocker]:
    verdict = documents.field(review_file, "Verdict")
    gaps = documents.field(review_file, "Blocking Evidence Gaps")
    if verdict == "INCONCLUSIVE" and decision != "close-inconclusive":
        return [
            Blocker(
                "inconclusive_review_verdict",
                f"{review_file}#Verdict",
                "Review verdict is INCONCLUSIVE but the decision is not close-inconclusive.",
                "Close inconclusive or complete enough review evidence to proceed.",
            )
        ]
    if verdict == "BLOCKED":
        return [_blocked_review_blocker(review_file)]
    if decision != "close-inconclusive" and _blocking_review_gaps(gaps):
        return [_blocked_review_blocker(review_file)]
    return []


def _blocked_review_blocker(review_file: Path) -> Blocker:
    return Blocker(
        "blocked_review",
        f"{review_file}#Verdict",
        "Review is blocked or records blocking evidence gaps.",
        "Resolve blocking review findings before advancing.",
    )


def _blocking_review_gaps(gaps: str) -> bool:
    return bool(gaps and gaps.strip().lower() not in NO_REVIEW_GAP_VALUES)


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


def _validate_repeated_negative_evidence(session: Session, round_dir: Path) -> list[Blocker]:
    evidence_file = round_dir / "evidence.md"
    repeated_section = documents.section(evidence_file, "Repeated Negative Evidence")
    if not _meaningful(repeated_section.content):
        return []
    if not _prior_continue_decision_exists(session):
        return []
    if _repeated_negative_acknowledged(round_dir / "decision.md", session.root / "progress.md"):
        return []
    return [
        Blocker(
            "unacknowledged_repeated_negative_evidence",
            f"rounds/{session.state.round:03d}/evidence.md#Repeated Negative Evidence",
            "Repeated negative evidence must be acknowledged after a prior continue decision.",
            "Acknowledge repeated negative evidence in decision.md or progress.md.",
        )
    ]


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
        for artifact_id in documents.extract_artifact_ids(text):
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


def _citation_sources(session_dir: Path, round_dir: Path) -> list[tuple[Path, str, str]]:
    sources: list[tuple[Path, str, str]] = []
    decision_file = round_dir / "decision.md"
    if decision_file.is_file():
        sources.append((decision_file, "Evidence", documents.field(decision_file, "Evidence")))
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


def _prior_continue_decision_exists(session: Session) -> bool:
    for round_number in range(1, session.state.round):
        decision_file = session.round_dir(round_number) / "decision.md"
        if decision_file.is_file() and documents.field(decision_file, "Decision") == "continue":
            return True
    return False


def _repeated_negative_acknowledged(decision_file: Path, progress_file: Path) -> bool:
    pattern = re.compile(r"repeated negative|repeated failure|continue justified", re.IGNORECASE)
    for path in (decision_file, progress_file):
        if path.is_file() and pattern.search(store.read_text(path)):
            return True
    return False

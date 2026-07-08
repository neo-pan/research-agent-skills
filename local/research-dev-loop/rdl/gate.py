"""Unified read-only gate reports for RDL session actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import artifacts, documents, memory, memory_report, readiness, semantic_review, summary
from .model import Blocker, RoundProfile, SessionPhase
from .protocol import descriptor
from .session import Session


@dataclass(frozen=True)
class GateFinding:
    severity: str
    category: str
    code: str
    location: str
    message: str
    next_action: str
    source: str = "deterministic"

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "category": self.category,
            "code": self.code,
            "location": self.location,
            "message": self.message,
            "next_action": self.next_action,
            "source": self.source,
        }

    def as_blocker(self) -> Blocker:
        return Blocker(self.code, self.location, self.message, self.next_action)


@dataclass(frozen=True)
class GateReport:
    action: str
    status: str
    findings: tuple[GateFinding, ...]
    blockers: tuple[Blocker, ...]
    warnings: tuple[str, ...]
    details: dict[str, Any]


def run(session: Session, action: str, *, next_mode: str | None = None, outcome: str | None = None) -> GateReport:
    """Return a profile-aware read-only gate report for an RDL action."""

    findings: list[GateFinding] = []
    findings.extend(_protocol_findings(session, action, outcome))

    prompt_context = memory.prompt_context(session)
    advisory_warnings = memory.advisory_warnings(
        session,
        next_mode=next_mode,
        prompt_context_value=prompt_context,
    )

    session_memory_report, summary_plan = memory_report.check(session)
    artifact_report = artifacts.check(session)
    findings.extend(_artifact_findings(artifact_report))
    findings.extend(_summary_findings(session, summary_plan))
    findings.extend(_memory_findings(session_memory_report))
    findings.extend(_state_findings(session, action))

    deterministic_report = _build_report(
        session,
        action,
        tuple(findings),
        advisory_warnings,
        session_memory_report,
        artifact_report,
        summary_plan,
    )
    semantic_report = semantic_review.run(session, action, deterministic_report)
    findings.extend(_semantic_findings(semantic_report))
    return _build_report(
        session,
        action,
        tuple(findings),
        advisory_warnings,
        session_memory_report,
        artifact_report,
        summary_plan,
        semantic_report=semantic_report,
    )


def _build_report(
    session: Session,
    action: str,
    findings: tuple[GateFinding, ...],
    advisory_warnings: tuple[str, ...],
    session_memory_report: memory_report.MemoryReport,
    artifact_report: artifacts.ArtifactReport,
    summary_plan: summary.SummaryPlan,
    *,
    semantic_report: semantic_review.SemanticReviewReport | None = None,
) -> GateReport:
    warning_codes = tuple(finding.code for finding in findings if finding.severity == "warning")
    blockers = tuple(finding.as_blocker() for finding in findings if finding.severity == "blocking")
    status = "blocked" if blockers else "needs_attention" if warning_codes or advisory_warnings else "ok"
    details: dict[str, Any] = {
        "gate_status": status,
        "findings": [finding.as_dict() for finding in findings],
        "memory": session_memory_report.details(),
        "artifact": artifact_report.details(),
        "summary": summary_plan.details(
            "up_to_date" if summary.progress_up_to_date(session, summary_plan) else "needs_update"
        ),
        "advisory_warnings": list(advisory_warnings),
    }
    if semantic_report is not None:
        details["semantic"] = semantic_report.details()
    return GateReport(
        action=action,
        status=status,
        findings=findings,
        blockers=blockers,
        warnings=tuple(dict.fromkeys((*advisory_warnings, *warning_codes))),
        details=details,
    )


def _protocol_findings(session: Session, action: str, outcome: str | None) -> tuple[GateFinding, ...]:
    if action == "doctor":
        blockers = readiness.check(session, "doctor-current")
    elif action == "advance":
        blockers = readiness.check(session, "advance")
    elif action == "close":
        blockers = _close_blockers(session, outcome)
    elif action == "handoff":
        blockers = ()
    else:
        blockers = (
            Blocker(
                "invalid_gate_action",
                action,
                "Gate action is unsupported.",
                "Fix the RDL gate caller.",
            ),
        )
    return tuple(_finding_from_blocker(blocker, category="protocol") for blocker in blockers)


def _close_blockers(session: Session, outcome: str | None) -> tuple[Blocker, ...]:
    if outcome is None:
        return (
            Blocker(
                "missing_close_outcome",
                "",
                "close gate requires positive, negative, or inconclusive outcome.",
                "Pass outcome=positive, outcome=negative, or outcome=inconclusive.",
            ),
        )
    if not descriptor.value_allowed("close-outcome", outcome):
        return (
            Blocker(
                "invalid_close_outcome",
                "",
                f"unsupported close outcome: {outcome}",
                "Use outcome=positive, outcome=negative, or outcome=inconclusive.",
            ),
        )

    blockers = list(readiness.check(session, "advance"))
    blockers.extend(readiness.check(session, "close", outcome=outcome))

    decision_file = session.round_dir() / "decision.md"
    expected_decision = f"close-{outcome}"
    if decision_file.is_file() and documents.field(decision_file, "Decision") != expected_decision:
        blockers.append(
            Blocker(
                "invalid_close_decision",
                f"{decision_file}#Decision",
                f"Close outcome requires Decision: {expected_decision}.",
                f"Run rdl decide {expected_decision} or update decision.md.",
            )
        )
    return tuple(blockers)


def _summary_findings(session: Session, summary_plan: summary.SummaryPlan) -> tuple[GateFinding, ...]:
    if summary_plan.blockers:
        return tuple(_finding_from_blocker(blocker, category="summary") for blocker in summary_plan.blockers)
    if summary_plan.total_rows > 0 and not summary.progress_up_to_date(session, summary_plan):
        return (
            GateFinding(
                "warning",
                "summary",
                "summary_needs_update",
                str(session.root / "progress.md"),
                "Deterministic session summary rows are not current.",
                "Run rdl memory --write to refresh managed summary blocks.",
            ),
        )
    return ()


def _artifact_findings(report: artifacts.ArtifactReport) -> tuple[GateFinding, ...]:
    return tuple(
        GateFinding(
            finding.severity,
            "artifact",
            finding.code,
            finding.location,
            finding.message,
            finding.next_action,
        )
        for finding in report.findings
    )


def _memory_findings(report: memory_report.MemoryReport) -> tuple[GateFinding, ...]:
    findings = [
        GateFinding(
            "warning",
            "memory",
            warning.code,
            warning.location,
            warning.message,
            warning.next_action,
        )
        for warning in report.quality_warnings
    ]
    locations = [f"progress.md#{section}" for section in report.progress_gaps]
    locations.extend(f"factors.md#{section}" for section in report.factor_gaps)
    if report.memory_status != "healthy":
        findings.insert(
            0,
            GateFinding(
                "warning",
                "memory",
                "session_memory_needs_attention",
                ", ".join(locations) if locations else "session memory",
                "Top-level session memory has gaps, stale deterministic summary rows, or quality warnings.",
                report.suggested_actions[0] if report.suggested_actions else "Run rdl memory --check.",
            ),
        )
    return tuple(findings)


def _semantic_findings(report: semantic_review.SemanticReviewReport) -> tuple[GateFinding, ...]:
    return tuple(
        GateFinding(
            finding.severity,
            "semantic",
            finding.code,
            finding.location,
            finding.message,
            finding.next_action,
            finding.source,
        )
        for finding in report.findings
    )


def _state_findings(session: Session, action: str) -> tuple[GateFinding, ...]:
    if action not in {"doctor", "handoff"}:
        return ()
    decision_file = session.round_dir() / "decision.md"
    decision = documents.field(decision_file, "Decision")
    if not decision:
        return ()
    if documents.validate("decision", decision_file, {"expected_closes": descriptor.expected_closes(session.state.mode)}):
        return ()
    if not _review_ready_for_profile(session):
        return ()
    if session.state.phase not in {
        SessionPhase.PLAN,
        SessionPhase.WORK,
        SessionPhase.EVIDENCE,
        SessionPhase.INTERPRET,
        SessionPhase.REVIEW,
    }:
        return ()
    return (
        GateFinding(
            "warning",
            "state",
            "round_content_ahead_of_state_phase",
            str(session.round_dir()),
            "Current round records include a completed decision/review while lifecycle state is still before decide/complete.",
            "Run rdl next when the round is ready, or inspect state/content consistency.",
        ),
    )


def _review_ready_for_profile(session: Session) -> bool:
    review_file = session.round_dir() / "review.md"
    if session.state.profile == RoundProfile.FULL_REVIEW or review_file.is_file():
        return not documents.validate("review", review_file)
    return True


def _finding_from_blocker(blocker: Blocker, *, category: str) -> GateFinding:
    return GateFinding(
        "blocking",
        category,
        blocker.code,
        blocker.file,
        blocker.message,
        blocker.next_action,
    )

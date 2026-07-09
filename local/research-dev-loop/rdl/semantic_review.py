"""Semantic review adapter seam for RDL gate reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import documents, review_pack
from .model import RoundProfile
from .protocol import descriptor
from .session import Session


NON_BLOCKING_GAP_VALUES = {"", "-", "none", "no", "no blocking gaps", "no blocking evidence gaps", "n/a", "not applicable", "none recorded"}


@dataclass(frozen=True)
class SemanticFinding:
    severity: str
    code: str
    location: str
    message: str
    next_action: str
    source: str

    def as_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "category": "semantic",
            "code": self.code,
            "location": self.location,
            "message": self.message,
            "next_action": self.next_action,
            "source": self.source,
        }


@dataclass(frozen=True)
class SemanticReviewReport:
    status: str
    adapter: str
    required: bool
    reviewed_artifacts: tuple[str, ...]
    recorded_findings: tuple[dict[str, str], ...]
    findings: tuple[SemanticFinding, ...]
    review_pack: review_pack.ReviewPack

    def details(self) -> dict[str, Any]:
        return {
            "semantic_status": self.status,
            "adapter": self.adapter,
            "required": self.required,
            "reviewed_artifacts": list(self.reviewed_artifacts),
            "recorded_findings": list(self.recorded_findings),
            "findings": [finding.as_dict() for finding in self.findings],
            "review_pack": self.review_pack.summary(),
        }


def run(session: Session, action: str, deterministic_gate_report: Any) -> SemanticReviewReport:
    """Run the first semantic adapter: a read-only adapter over review.md."""

    pack = review_pack.build(session, action, deterministic_gate_report)
    required = _semantic_review_required(session, action, deterministic_gate_report)
    review_file = session.round_dir() / "review.md"
    adapter = documents.field(review_file, "Review Mode") if review_file.is_file() else "none"
    findings: list[SemanticFinding] = []

    if required and not review_file.is_file():
        findings.append(
            SemanticFinding(
                "blocking",
                "missing_semantic_review",
                str(review_file),
                "A semantic review result is required for this gate.",
                "Run rdl review and record the review adapter and findings.",
                "review-md",
            )
        )
        return _report(required, adapter, (), (), findings, pack)

    review_blockers = documents.validate("review", review_file) if review_file.is_file() else []
    if required and review_blockers:
        findings.append(
            SemanticFinding(
                "blocking",
                "invalid_semantic_review_record",
                str(review_file),
                "review.md is present but is not a complete semantic review record.",
                "Complete review.md before using this gate.",
                "review-md",
            )
        )
        return _report(required, adapter, (), (), findings, pack)

    if not review_file.is_file() or review_blockers:
        return _report(required, adapter, (), (), findings, pack)

    artifacts = _split_field(documents.field(review_file, "Artifacts Reviewed"))
    decision = documents.field(session.round_dir() / "decision.md", "Decision")
    verdict = documents.field(review_file, "Verdict")
    gaps = documents.field(review_file, "Blocking Evidence Gaps")
    fresh_evidence = documents.field(review_file, "Fresh Evidence")
    staleness = documents.field(review_file, "Staleness Signal")
    reuse_risk = documents.field(review_file, "Direction Reuse Risk")
    recommended = documents.field(review_file, "Recommended Decision")
    decision_file = session.round_dir() / "decision.md"
    direction_changed = documents.field(decision_file, "Direction changed")
    stall_response = documents.field(decision_file, "Stall response")
    recorded_findings = _recorded_findings(review_file, adapter)

    findings.append(
        SemanticFinding(
            "note",
            "semantic_review_recorded",
            str(review_file),
            f"Semantic review is recorded using the {adapter} adapter.",
            "Use the recorded review findings when deciding the next RDL action.",
            adapter,
        )
    )
    if verdict == "BLOCKED":
        findings.append(
            SemanticFinding(
                "blocking",
                "semantic_review_blocked",
                f"{review_file}#Verdict",
                "The semantic review verdict is BLOCKED.",
                "Resolve blocking review findings before advancing.",
                adapter,
            )
        )
    elif verdict == "INCONCLUSIVE" and decision != "close-inconclusive":
        findings.append(
            SemanticFinding(
                "blocking",
                "semantic_review_inconclusive",
                f"{review_file}#Verdict",
                "The semantic review verdict is INCONCLUSIVE.",
                "Close inconclusive or add enough evidence for a non-inconclusive decision.",
                adapter,
            )
        )
    if _blocking_gaps(gaps):
        severity = "warning" if decision == "close-inconclusive" else "blocking"
        findings.append(
            SemanticFinding(
                severity,
                "semantic_review_evidence_gaps",
                f"{review_file}#Blocking Evidence Gaps",
                "The semantic review records blocking evidence gaps.",
                "Resolve or explicitly close inconclusive before advancing.",
                adapter,
            )
        )
    if _meaningful(recommended) and _meaningful(decision) and recommended != decision:
        findings.append(
            SemanticFinding(
                "blocking",
                "semantic_review_decision_mismatch",
                f"{review_file}#Recommended Decision",
                "The semantic review recommended decision does not match decision.md.",
                "Align review.md and decision.md before advancing.",
                adapter,
            )
        )
    if _review_records_attention_risk(fresh_evidence, staleness, reuse_risk):
        findings.append(
            SemanticFinding(
                "warning",
                "semantic_review_staleness_risk",
                str(review_file),
                "The semantic review records weak fresh evidence, staleness, or high direction reuse risk.",
                "Record a stall response, change direction, or close the session if the risk is decision-relevant.",
                adapter,
            )
        )
    if _review_records_stale_continue_risk(fresh_evidence, staleness, reuse_risk) and _continuing_current_direction(
        decision,
        direction_changed,
    ) and not _meaningful_stall_response(stall_response):
        findings.append(
            SemanticFinding(
                "blocking",
                "semantic_review_missing_stall_response",
                f"{decision_file}#Stall response",
                "The semantic review records stale continuation risk without a meaningful stall response.",
                "Record a stall response, change direction, or close the session.",
                adapter,
            )
        )

    return _report(required, adapter, artifacts, recorded_findings, findings, pack)


def _semantic_review_required(session: Session, action: str, deterministic_gate_report: Any) -> bool:
    if _fatal_gate_setup_blocked(deterministic_gate_report):
        return False
    if action == "handoff":
        return False
    if action == "close":
        return True
    if session.state.profile == RoundProfile.FULL_REVIEW:
        return True
    return False


def _fatal_gate_setup_blocked(deterministic_gate_report: Any) -> bool:
    fatal_codes = {"invalid_gate_action", "missing_close_outcome", "invalid_close_outcome"}
    return any(blocker.code in fatal_codes for blocker in getattr(deterministic_gate_report, "blockers", ()))


def _report(
    required: bool,
    adapter: str,
    artifacts: tuple[str, ...],
    recorded_findings: tuple[dict[str, str], ...],
    findings: list[SemanticFinding],
    pack: review_pack.ReviewPack,
) -> SemanticReviewReport:
    status = "blocked" if any(finding.severity == "blocking" for finding in findings) else "needs_attention" if any(
        finding.severity == "warning" for finding in findings
    ) else "ok"
    return SemanticReviewReport(status, adapter, required, artifacts, recorded_findings, tuple(findings), pack)


def _recorded_findings(review_file: Any, adapter: str) -> tuple[dict[str, str], ...]:
    parsed = documents.section(review_file, "Returned Review Findings")
    lines = [line.strip() for line in parsed.content.splitlines() if line.strip()]
    if len(lines) == 1 and lines[0].lower() in {"none", "none recorded", "- none"}:
        return ()
    findings = []
    for line in lines:
        if not line.startswith("- "):
            continue
        parts = [part.strip() for part in line[2:].split("|")]
        if len(parts) != 5:
            continue
        severity, category, location, claim, required_resolution = parts
        findings.append(
            {
                "severity": severity,
                "category": category,
                "location": location,
                "claim": claim,
                "required_resolution": required_resolution,
                "source": adapter,
            }
        )
    return tuple(findings)


def _split_field(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _blocking_gaps(value: str) -> bool:
    return value.strip().lower() not in NON_BLOCKING_GAP_VALUES


def _review_records_attention_risk(fresh_evidence: str, staleness: str, reuse_risk: str) -> bool:
    return fresh_evidence in {"mixed", "no"} or _review_records_stale_continue_risk(fresh_evidence, staleness, reuse_risk)


def _review_records_stale_continue_risk(fresh_evidence: str, staleness: str, reuse_risk: str) -> bool:
    return fresh_evidence == "no" or staleness in {"possible", "repeated"} or reuse_risk == "high"


def _continuing_current_direction(decision: str, direction_changed: str) -> bool:
    if descriptor.direction_change_ends_current_direction(direction_changed):
        return False
    return descriptor.decision_continues_current_direction(decision)


def _meaningful(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(normalized and normalized not in {"-", "...", "tbd", "todo", "n/a", "not applicable", "none recorded"})


def _meaningful_stall_response(value: str) -> bool:
    normalized = value.strip().lower()
    if not _meaningful(value):
        return False
    return normalized not in {"no staleness signal", "no staleness signals", "no stale signal", "no stale signals"}

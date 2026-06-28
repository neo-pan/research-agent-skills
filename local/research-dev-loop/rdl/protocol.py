"""RDL protocol descriptor.

This module owns protocol facts so validators, integrity logic, templates, and
tests do not each maintain their own copies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .model import SessionMode

IntegrityPolicy = Literal["cli_owned", "append_only", "managed_prefix", "human_owned"]


@dataclass(frozen=True)
class ProtocolDescriptor:
    def required_session_files(self) -> tuple[str, ...]:
        return (
            "state.json",
            "mission.md",
            "factors.md",
            "artifact-manifest.json",
            "decision-ledger.md",
            "progress.md",
        )

    def optional_session_files(self) -> tuple[str, ...]:
        return ("final-report.md",)

    def round_file_names(self) -> tuple[str, ...]:
        return (
            "prompt.md",
            "intent.md",
            "work.md",
            "evidence.md",
            "interpretation.md",
            "review.md",
            "decision.md",
        )

    def completed_round_files(self, mode: SessionMode | str) -> tuple[str, ...]:
        mode_value = _mode_value(mode)
        if mode_value == SessionMode.RESEARCH.value:
            return ("prompt.md", "evidence.md", "interpretation.md", "review.md", "decision.md")
        if mode_value == SessionMode.BUILD.value:
            return ("prompt.md", "intent.md", "work.md", "evidence.md", "review.md", "decision.md")
        return ()

    def required_fields(self, kind: str) -> tuple[str, ...]:
        if kind == "review":
            return (
                "Reviewer",
                "Review Mode",
                "Review Scope",
                "Artifacts Reviewed",
                "Verdict",
                "Decision Reviewed",
                "Evidence Reviewed",
                "Blocking Evidence Gaps",
                "Implementation Findings",
                "Evaluation Integrity Findings",
                "Overclaim Risks",
                "Readiness Level",
                "Recommended Decision",
            )
        if kind == "decision":
            return (
                "Decision",
                "Closes",
                "Evidence",
                "Uncertainty",
                "What this rules out",
                "What remains unknown",
                "Recommended next loop",
                "Next smallest step",
            )
        return ()

    def required_sections(self, kind: str) -> tuple[str, ...]:
        if kind == "final-report":
            return (
                "Outcome",
                "Claim or Capability Closed",
                "Evidence Cited",
                "Missing Evidence and Confounders",
                "Negative, Null, or Inconclusive Results",
                "Open Questions",
                "Deferred Items",
                "Close Checklist",
            )
        if kind == "progress":
            return ("Active", "Completed", "Blocked", "Deferred", "Open Questions")
        return ()

    def allowed_values(self, kind: str) -> tuple[str, ...]:
        values = {
            "review-mode": ("manual", "checklist", "phase-review", "subagent", "project-adapter"),
            "review-verdict": ("PASS", "PASS_WITH_NOTES", "BLOCKED", "INCONCLUSIVE"),
            "decision-type": (
                "continue",
                "pivot",
                "narrow",
                "broaden",
                "diagnose",
                "build",
                "profile",
                "rerun",
                "accept",
                "reject",
                "close-positive",
                "close-negative",
                "close-inconclusive",
            ),
            "close-outcome": ("positive", "negative", "inconclusive"),
            "recommended-next-loop": ("research", "build", "none"),
        }
        return values.get(kind, ())

    def value_allowed(self, kind: str, value: str) -> bool:
        return value in self.allowed_values(kind)

    def expected_closes(self, mode: SessionMode | str) -> str:
        mode_value = _mode_value(mode)
        if mode_value == SessionMode.RESEARCH.value:
            return "claim"
        if mode_value == SessionMode.BUILD.value:
            return "capability"
        return ""

    def policy_for_path(self, path: str) -> IntegrityPolicy:
        if path == "state.json":
            return "cli_owned"
        if path == "decision-ledger.md":
            return "append_only"
        if self.round_path_known(path) and path.endswith("/prompt.md"):
            return "managed_prefix"
        return "human_owned"

    def session_path_known(self, path: str) -> bool:
        return path in (*self.required_session_files(), *self.optional_session_files())

    def round_path_known(self, path: str) -> bool:
        match = re.fullmatch(r"rounds/[0-9]{3}/([^/]+)", path)
        if not match:
            return False
        return match.group(1) in self.round_file_names()

    def path_known(self, path: str) -> bool:
        if not _safe_relative_protocol_path(path):
            return False
        return self.session_path_known(path) or self.round_path_known(path)

    def readiness_plan(self, name: str) -> tuple[str, ...]:
        plans = {
            "doctor-current": (
                "review",
                "decision",
                "mode-minimums",
                "round-evidence-discipline",
                "artifact-citations",
                "close-if-decision",
            ),
            "advance": (
                "review",
                "decision",
                "review-decision-alignment",
                "mode-minimums",
                "round-evidence-discipline",
                "artifact-citations",
            ),
            "guard-stop-advance": (
                "review",
                "decision",
                "review-decision-alignment",
                "mode-minimums",
                "round-evidence-discipline",
                "artifact-citations",
            ),
            "close": (
                "final-report",
                "close-evidence-discipline",
                "progress-close-readiness",
                "artifact-citations",
                "repeated-negative-evidence",
            ),
            "guard-stop-close": (
                "final-report",
                "close-evidence-discipline",
                "progress-close-readiness",
                "artifact-citations",
                "repeated-negative-evidence",
            ),
        }
        return plans.get(name, ())


def _mode_value(mode: SessionMode | str) -> str:
    return mode.value if isinstance(mode, SessionMode) else str(mode)


def _safe_relative_protocol_path(path: str) -> bool:
    if path in {"", ".", ".."}:
        return False
    if path.startswith("/") or path.startswith("./") or path.startswith("../"):
        return False
    parts = path.split("/")
    return "." not in parts and ".." not in parts


descriptor = ProtocolDescriptor()

"""RDL protocol descriptor.

This module owns protocol facts so validators, integrity logic, templates, and
tests do not each maintain their own copies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .model import RoundProfile, SessionMode

IntegrityPolicy = Literal["cli_owned", "append_only", "managed_prefix", "human_owned"]


@dataclass(frozen=True)
class ModeSpec:
    completed_round_files: tuple[str, ...]
    expected_closes: str
    prompt_expected_exit_decision: str


@dataclass(frozen=True)
class ProfileSpec:
    completed_round_files_by_mode: dict[str, tuple[str, ...]]
    prompt_expected_exit_decision_by_mode: dict[str, str]


@dataclass(frozen=True)
class DocumentSpec:
    required_fields: tuple[str, ...] = ()
    required_sections: tuple[str, ...] = ()
    allowed_values: dict[str, tuple[str, ...]] | None = None

    def values_for_field(self, field_name: str) -> tuple[str, ...]:
        return (self.allowed_values or {}).get(field_name, ())


SESSION_FILES = (
    "state.json",
    "mission.md",
    "factors.md",
    "artifact-manifest.json",
    "decision-ledger.md",
    "progress.md",
)

OPTIONAL_SESSION_FILES = ("final-report.md",)

ROUND_FILES = (
    "prompt.md",
    "intent.md",
    "work.md",
    "evidence.md",
    "interpretation.md",
    "review.md",
    "decision.md",
)

MODE_SPECS = {
    SessionMode.RESEARCH.value: ModeSpec(
        completed_round_files=("prompt.md", "evidence.md", "interpretation.md", "review.md", "decision.md"),
        expected_closes="claim",
        prompt_expected_exit_decision="claim decision with evidence and uncertainty",
    ),
    SessionMode.BUILD.value: ModeSpec(
        completed_round_files=("prompt.md", "intent.md", "work.md", "evidence.md", "review.md", "decision.md"),
        expected_closes="capability",
        prompt_expected_exit_decision="capability decision with verification evidence",
    ),
}

PROFILE_SPECS = {
    RoundProfile.FULL_REVIEW.value: ProfileSpec(
        completed_round_files_by_mode={
            SessionMode.RESEARCH.value: MODE_SPECS[SessionMode.RESEARCH.value].completed_round_files,
            SessionMode.BUILD.value: MODE_SPECS[SessionMode.BUILD.value].completed_round_files,
        },
        prompt_expected_exit_decision_by_mode={
            SessionMode.RESEARCH.value: MODE_SPECS[SessionMode.RESEARCH.value].prompt_expected_exit_decision,
            SessionMode.BUILD.value: MODE_SPECS[SessionMode.BUILD.value].prompt_expected_exit_decision,
        },
    ),
    RoundProfile.CHECKPOINT.value: ProfileSpec(
        completed_round_files_by_mode={
            SessionMode.RESEARCH.value: ("prompt.md", "evidence.md", "decision.md"),
            SessionMode.BUILD.value: ("prompt.md", "evidence.md", "decision.md"),
        },
        prompt_expected_exit_decision_by_mode={
            SessionMode.RESEARCH.value: "checkpoint decision with evidence",
            SessionMode.BUILD.value: "checkpoint decision with evidence",
        },
    ),
    RoundProfile.BUILD_UPDATE.value: ProfileSpec(
        completed_round_files_by_mode={
            SessionMode.BUILD.value: ("prompt.md", "intent.md", "work.md", "evidence.md", "decision.md"),
        },
        prompt_expected_exit_decision_by_mode={
            SessionMode.BUILD.value: "build update decision with verification evidence",
        },
    ),
}

VALUE_SETS = {
    "round-profile": ("full-review", "checkpoint", "build-update"),
    "review-mode": ("manual", "checklist", "phase-review", "subagent", "project-adapter"),
    "review-verdict": ("PASS", "PASS_WITH_NOTES", "BLOCKED", "INCONCLUSIVE"),
    "fresh-evidence": ("yes", "mixed", "no"),
    "staleness-signal": ("none", "possible", "repeated"),
    "direction-reuse-risk": ("low", "medium", "high"),
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
    "direction-changed": ("yes", "no", "closing"),
}

DOCUMENT_SPECS = {
    "review": DocumentSpec(
        required_fields=(
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
            "Fresh Evidence",
            "Staleness Signal",
            "Direction Reuse Risk",
            "Readiness Level",
            "Recommended Decision",
        ),
        allowed_values={
            "Review Mode": VALUE_SETS["review-mode"],
            "Verdict": VALUE_SETS["review-verdict"],
            "Fresh Evidence": VALUE_SETS["fresh-evidence"],
            "Staleness Signal": VALUE_SETS["staleness-signal"],
            "Direction Reuse Risk": VALUE_SETS["direction-reuse-risk"],
        },
    ),
    "decision": DocumentSpec(
        required_fields=(
            "Decision",
            "Closes",
            "Evidence",
            "Uncertainty",
            "What this rules out",
            "What remains unknown",
            "Direction changed",
            "Prior directions checked",
            "Stall response",
            "Recommended next loop",
            "Next smallest step",
        ),
        allowed_values={
            "Decision": VALUE_SETS["decision-type"],
            "Recommended next loop": VALUE_SETS["recommended-next-loop"],
            "Direction changed": VALUE_SETS["direction-changed"],
        },
    ),
    "final-report": DocumentSpec(
        required_sections=(
            "Outcome",
            "Claim or Capability Closed",
            "Evidence Cited",
            "Missing Evidence and Confounders",
            "Negative, Null, or Inconclusive Results",
            "Open Questions",
            "Deferred Items",
            "Directions Tried And Stall Responses",
            "Reusable Lessons",
            "Close Checklist",
        ),
    ),
    "progress": DocumentSpec(
        required_sections=("Active", "Completed", "Blocked", "Deferred", "Open Questions", "Directions Tried", "Staleness Watch"),
    ),
}

READINESS_PLANS = {
    "doctor-current": (
        "review",
        "decision",
        "staleness-response",
        "mode-minimums",
        "round-evidence-discipline",
        "artifact-citations",
        "close-if-decision",
    ),
    "advance": (
        "review",
        "decision",
        "review-decision-alignment",
        "staleness-response",
        "mode-minimums",
        "round-evidence-discipline",
        "artifact-citations",
        "close-if-decision",
    ),
    "guard-stop-advance": (
        "review",
        "decision",
        "review-decision-alignment",
        "staleness-response",
        "mode-minimums",
        "round-evidence-discipline",
        "artifact-citations",
        "close-if-decision",
    ),
    "close": (
        "full-review-close-profile",
        "final-report",
        "close-evidence-discipline",
        "progress-close-readiness",
        "artifact-citations",
        "repeated-negative-evidence",
    ),
    "guard-stop-close": (
        "full-review-close-profile",
        "final-report",
        "close-evidence-discipline",
        "progress-close-readiness",
        "artifact-citations",
        "repeated-negative-evidence",
    ),
}

CLOSE_OUTCOME_BY_DECISION = {
    "close-positive": "positive",
    "close-negative": "negative",
    "close-inconclusive": "inconclusive",
}


@dataclass(frozen=True)
class ProtocolDescriptor:
    def required_session_files(self) -> tuple[str, ...]:
        return SESSION_FILES

    def optional_session_files(self) -> tuple[str, ...]:
        return OPTIONAL_SESSION_FILES

    def initialized_session_templates(self) -> tuple[str, ...]:
        return tuple(
            file_name
            for file_name in self.required_session_files()
            if file_name not in {"state.json", "mission.md"}
        )

    def round_file_names(self) -> tuple[str, ...]:
        return ROUND_FILES

    def completed_round_files(
        self,
        mode: SessionMode | str,
        profile: RoundProfile | str = RoundProfile.FULL_REVIEW,
    ) -> tuple[str, ...]:
        mode_value = _mode_value(mode)
        profile_spec = self.profile_spec(profile)
        if profile_spec is None:
            return ()
        return profile_spec.completed_round_files_by_mode.get(mode_value, ())

    def required_fields(self, kind: str) -> tuple[str, ...]:
        spec = self.document_spec(kind)
        return spec.required_fields if spec is not None else ()

    def required_sections(self, kind: str) -> tuple[str, ...]:
        spec = self.document_spec(kind)
        return spec.required_sections if spec is not None else ()

    def allowed_values(self, kind: str) -> tuple[str, ...]:
        return VALUE_SETS.get(kind, ())

    def value_allowed(self, kind: str, value: str) -> bool:
        return value in self.allowed_values(kind)

    def expected_closes(self, mode: SessionMode | str) -> str:
        spec = self.mode_spec(mode)
        return spec.expected_closes if spec is not None else ""

    def prompt_expected_exit_decision(
        self,
        mode: SessionMode | str,
        profile: RoundProfile | str = RoundProfile.FULL_REVIEW,
    ) -> str:
        if not self.profile_allowed_for_mode(mode, profile):
            return ""
        spec = self.profile_spec(profile)
        return spec.prompt_expected_exit_decision_by_mode.get(_mode_value(mode), "") if spec is not None else ""

    def policy_for_path(self, path: str) -> IntegrityPolicy:
        policy = self.path_policy(path)
        if policy is not None:
            return policy
        return "human_owned"

    def path_policy(self, path: str) -> IntegrityPolicy | None:
        if not self.path_known(path):
            return None
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

    def path_safe_relative(self, path: str) -> bool:
        return _safe_relative_protocol_path(path)

    def readiness_plan(self, name: str) -> tuple[str, ...]:
        return READINESS_PLANS.get(name, ())

    def document_spec(self, kind: str) -> DocumentSpec | None:
        return DOCUMENT_SPECS.get(kind)

    def mode_spec(self, mode: SessionMode | str) -> ModeSpec | None:
        return MODE_SPECS.get(_mode_value(mode))

    def profile_spec(self, profile: RoundProfile | str) -> ProfileSpec | None:
        return PROFILE_SPECS.get(_profile_value(profile))

    def profile_allowed_for_mode(self, mode: SessionMode | str, profile: RoundProfile | str) -> bool:
        mode_value = _mode_value(mode)
        spec = self.profile_spec(profile)
        return spec is not None and mode_value in spec.completed_round_files_by_mode

    def close_outcome_for_decision(self, decision: str) -> str:
        return CLOSE_OUTCOME_BY_DECISION.get(decision, "")


def _mode_value(mode: SessionMode | str) -> str:
    return mode.value if isinstance(mode, SessionMode) else str(mode)


def _profile_value(profile: RoundProfile | str) -> str:
    return profile.value if isinstance(profile, RoundProfile) else str(profile)


def _safe_relative_protocol_path(path: str) -> bool:
    if path in {"", ".", ".."}:
        return False
    if path.startswith("/") or path.startswith("./") or path.startswith("../"):
        return False
    parts = path.split("/")
    return "." not in parts and ".." not in parts


descriptor = ProtocolDescriptor()

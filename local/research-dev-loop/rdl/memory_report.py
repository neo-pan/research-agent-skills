"""Session-memory health reports for RDL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import documents, summary

if TYPE_CHECKING:
    from .session import Session


PROGRESS_MANUAL_SECTIONS = ("Active", "Blocked", "Deferred")
FACTOR_SECTIONS = (
    "Model or Algorithm",
    "Dataset or Workload",
    "Seed and Sampling",
    "Hardware or Backend",
    "Prompt or Policy Version",
    "Baseline",
    "Candidate-Visible Context",
    "Metric Definition",
    "Evaluator or Validator Version",
    "Environment",
    "Known Non-Determinism",
)


@dataclass(frozen=True)
class MemoryReport:
    memory_status: str
    progress_gaps: tuple[str, ...]
    factor_gaps: tuple[str, ...]
    deterministic_updates: dict[str, int]
    suggested_actions: tuple[str, ...]

    def details(self, status: str | None = None) -> dict[str, object]:
        return {
            "memory_status": self.memory_status if status is None else status,
            "progress_gaps": list(self.progress_gaps),
            "factor_gaps": list(self.factor_gaps),
            "deterministic_updates": self.deterministic_updates,
            "suggested_actions": list(self.suggested_actions),
        }


def check(session: "Session") -> tuple[MemoryReport, summary.SummaryPlan]:
    summary_plan = summary.check(session)
    return _report(session, summary_plan), summary_plan


def report_after_write(session: "Session", summary_plan: summary.SummaryPlan) -> MemoryReport:
    return _report(session, summary_plan, status="written")


def _report(session: "Session", summary_plan: summary.SummaryPlan, status: str | None = None) -> MemoryReport:
    progress_gaps = _progress_gaps(session)
    factor_gaps = _factor_gaps(session)
    deterministic_updates = {section: len(rows) for section, rows in summary_plan.rows.items()}
    needs_summary = not summary.progress_up_to_date(session, summary_plan)
    memory_status = status or ("needs_attention" if progress_gaps or factor_gaps or needs_summary else "healthy")
    return MemoryReport(
        memory_status=memory_status,
        progress_gaps=progress_gaps,
        factor_gaps=factor_gaps,
        deterministic_updates=deterministic_updates,
        suggested_actions=_suggested_actions(progress_gaps, factor_gaps, deterministic_updates, needs_summary),
    )


def _progress_gaps(session: "Session") -> tuple[str, ...]:
    progress_file = session.root / "progress.md"
    return tuple(section for section in PROGRESS_MANUAL_SECTIONS if not documents.section_has_content(progress_file, section))


def _factor_gaps(session: "Session") -> tuple[str, ...]:
    factors_file = session.root / "factors.md"
    return tuple(section for section in FACTOR_SECTIONS if not documents.section_has_content(factors_file, section))


def _suggested_actions(
    progress_gaps: tuple[str, ...],
    factor_gaps: tuple[str, ...],
    deterministic_updates: dict[str, int],
    needs_summary: bool,
) -> tuple[str, ...]:
    actions: list[str] = []
    if needs_summary and any(count > 0 for count in deterministic_updates.values()):
        actions.append("Run rdl memory --write to refresh deterministic progress summary blocks.")
    if progress_gaps:
        sections = ", ".join(progress_gaps)
        actions.append(f"Manually update progress.md sections: {sections}.")
    if factor_gaps:
        actions.append("Record decision-relevant factor changes in factors.md before advancing the session.")
    if not actions:
        actions.append("Run rdl doctor.")
    return tuple(actions)

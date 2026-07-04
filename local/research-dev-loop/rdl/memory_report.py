"""Session-memory health reports for RDL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import documents, session_memory_edit, summary
from .protocol import descriptor

if TYPE_CHECKING:
    from .session import Session


PROGRESS_MANUAL_SECTIONS = session_memory_edit.PROGRESS_MANUAL_SECTIONS
FACTOR_SECTIONS = session_memory_edit.FACTOR_SECTIONS


@dataclass(frozen=True)
class MemoryQualityWarning:
    code: str
    location: str
    message: str
    next_action: str

    def details(self) -> dict[str, str]:
        return {
            "code": self.code,
            "location": self.location,
            "message": self.message,
            "next_action": self.next_action,
        }


@dataclass(frozen=True)
class MemoryReport:
    memory_status: str
    progress_gaps: tuple[str, ...]
    factor_gaps: tuple[str, ...]
    deterministic_updates: dict[str, int]
    quality_warnings: tuple[MemoryQualityWarning, ...]
    suggested_actions: tuple[str, ...]

    def details(self, status: str | None = None) -> dict[str, object]:
        return {
            "memory_status": self.memory_status if status is None else status,
            "progress_gaps": list(self.progress_gaps),
            "factor_gaps": list(self.factor_gaps),
            "deterministic_updates": self.deterministic_updates,
            "quality_warnings": [warning.details() for warning in self.quality_warnings],
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
    quality_warnings = _quality_warnings(session)
    deterministic_updates = {section: len(rows) for section, rows in summary_plan.rows.items()}
    needs_summary = not summary.progress_up_to_date(session, summary_plan)
    memory_status = status or ("needs_attention" if progress_gaps or factor_gaps or needs_summary or quality_warnings else "healthy")
    return MemoryReport(
        memory_status=memory_status,
        progress_gaps=progress_gaps,
        factor_gaps=factor_gaps,
        deterministic_updates=deterministic_updates,
        quality_warnings=quality_warnings,
        suggested_actions=_suggested_actions(progress_gaps, factor_gaps, deterministic_updates, needs_summary, quality_warnings),
    )


def _progress_gaps(session: "Session") -> tuple[str, ...]:
    progress_file = session.root / "progress.md"
    return tuple(section for section in PROGRESS_MANUAL_SECTIONS if not documents.section_has_content(progress_file, section))


def _factor_gaps(session: "Session") -> tuple[str, ...]:
    factors_file = session.root / "factors.md"
    return tuple(section for section in FACTOR_SECTIONS if not documents.section_has_content(factors_file, section))


def _quality_warnings(session: "Session") -> tuple[MemoryQualityWarning, ...]:
    warnings: list[MemoryQualityWarning] = []
    progress_file = session.root / "progress.md"
    warnings.extend(_malformed_progress_table_warnings(progress_file))
    duplicates = _duplicate_open_questions(progress_file)
    if duplicates:
        warnings.append(
            MemoryQualityWarning(
                "duplicate_open_questions",
                "progress.md#Open Questions",
                "Open Questions contains duplicate questions after normalization.",
                "Merge duplicate open questions or mark one resolved.",
            )
        )
    return tuple(warnings)


def _malformed_progress_table_warnings(progress_file) -> tuple[MemoryQualityWarning, ...]:
    warnings: list[MemoryQualityWarning] = []
    progress_spec = descriptor.document_spec("progress")
    for section in progress_spec.required_sections if progress_spec is not None else ():
        table = _table(documents.section(progress_file, section).content)
        if not table.present:
            continue
        for row_index, row in enumerate(table.rows, start=1):
            if len(row.cells) != len(table.headers):
                warnings.append(
                    MemoryQualityWarning(
                        "malformed_progress_table_row",
                        f"progress.md#{section} row {row_index}",
                        f"{section} contains a table row with {len(row.cells)} cells, expected {len(table.headers)}.",
                        "Rewrite the row with the canonical number of table cells.",
                    )
                )
                break
    return tuple(warnings)


def _duplicate_open_questions(progress_file) -> tuple[str, ...]:
    rows = _table_rows(documents.section(progress_file, "Open Questions").content)
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for row in rows:
        question = row.get("question", "")
        normalized = _normalize_question(question)
        if not normalized:
            continue
        if normalized in seen:
            duplicates.append(question)
        else:
            seen[normalized] = question
    return tuple(duplicates)


@dataclass(frozen=True)
class _TableRow:
    cells: tuple[str, ...]


@dataclass(frozen=True)
class _Table:
    present: bool
    headers: tuple[str, ...]
    rows: tuple[_TableRow, ...]


def _table_rows(markdown: str) -> list[dict[str, str]]:
    table = _table(markdown)
    if not table.headers:
        return []
    rows: list[dict[str, str]] = []
    for row in table.rows:
        if not any(cell.strip() for cell in row.cells):
            continue
        rows.append({table.headers[index]: row.cells[index].strip() if index < len(row.cells) else "" for index in range(len(table.headers))})
    return rows


def _table(markdown: str) -> _Table:
    lines = [line.strip() for line in markdown.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return _Table(False, (), ())
    headers = tuple(_normalize_header(cell) for cell in _split_row(lines[0]))
    rows: list[_TableRow] = []
    for line in lines[1:]:
        if _table_separator(line):
            continue
        rows.append(_TableRow(tuple(_split_row(line))))
    return _Table(True, headers, tuple(rows))


def _split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\|[ \t:|-]+\|[ \t|:-]*", line.strip()))


def _normalize_header(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _normalize_question(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.strip().lower())
    normalized = " ".join(normalized.split())
    if normalized in {"", "none", "none recorded", "no open questions"}:
        return ""
    return normalized


def _suggested_actions(
    progress_gaps: tuple[str, ...],
    factor_gaps: tuple[str, ...],
    deterministic_updates: dict[str, int],
    needs_summary: bool,
    quality_warnings: tuple[MemoryQualityWarning, ...],
) -> tuple[str, ...]:
    actions: list[str] = []
    if needs_summary and any(count > 0 for count in deterministic_updates.values()):
        actions.append("Run rdl memory --write to refresh deterministic progress summary blocks.")
    if progress_gaps:
        sections = ", ".join(progress_gaps)
        actions.append(f"Record progress memory with rdl progress for sections: {sections}.")
    if factor_gaps:
        first_gap = factor_gaps[0]
        actions.append(f"Record factor memory with rdl factors set --section \"{first_gap}\" --value <text>.")
    actions.extend(warning.next_action for warning in quality_warnings)
    if not actions:
        actions.append("Run rdl doctor.")
    return tuple(actions)

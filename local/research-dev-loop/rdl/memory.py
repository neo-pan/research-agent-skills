"""Deterministic session-memory helpers for RDL prompts and warnings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import documents, store

if TYPE_CHECKING:
    from .session import Session


NONE_RECORDED = "none recorded"


@dataclass(frozen=True)
class PromptContext:
    claim_or_capability: str = NONE_RECORDED
    open_questions: str = NONE_RECORDED
    known_evidence_gaps: str = NONE_RECORDED
    directions_tried: str = NONE_RECORDED
    staleness_watch: str = NONE_RECORDED
    next_smallest_step: str = NONE_RECORDED

    def carry_forward_fields(self) -> tuple[str, ...]:
        return (
            self.open_questions,
            self.known_evidence_gaps,
            self.directions_tried,
            self.staleness_watch,
        )


def prompt_context(session: "Session", round_number: int | None = None) -> PromptContext:
    current_round = session.state.round if round_number is None else round_number
    progress_file = session.root / "progress.md"
    decision_file = session.round_dir(current_round) / "decision.md"
    evidence_file = session.round_dir(current_round) / "evidence.md"

    return PromptContext(
        claim_or_capability=_progress_section_summary(progress_file, "Active", preferred=("claim or capability", "item")),
        open_questions=_progress_section_summary(progress_file, "Open Questions", preferred=("question",)),
        known_evidence_gaps=_known_evidence_gaps(decision_file, evidence_file),
        directions_tried=_progress_section_summary(progress_file, "Directions Tried", preferred=("direction",)),
        staleness_watch=_progress_section_summary(progress_file, "Staleness Watch", preferred=("signal",)),
        next_smallest_step=_field_or_none(decision_file, "Next smallest step"),
    )


def advisory_warnings(
    session: "Session",
    *,
    next_mode: str | None = None,
    prompt_context_value: PromptContext | None = None,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if session.state.round >= 3 and _progress_memory_empty(session.root / "progress.md"):
        warnings.append("empty_progress_memory_after_multiple_rounds")
    if session.state.round >= 2 and _factors_memory_empty(session.root / "factors.md"):
        warnings.append("empty_factors_memory_after_first_round")

    context = prompt_context_value if prompt_context_value is not None else prompt_context(session)
    if _all_none(context.carry_forward_fields()) and _historical_handoff_exists(session):
        warnings.append("empty_prompt_carry_forward_despite_prior_state")

    target_mode = next_mode or str(session.state.mode)
    next_loop = documents.field(session.round_dir() / "decision.md", "Recommended next loop")
    if _meaningful(next_loop) and next_loop != "none" and next_loop != target_mode:
        warnings.append("recommended_next_loop_differs_from_next_mode")

    return tuple(dict.fromkeys(warnings))


def _known_evidence_gaps(decision_file: Path, evidence_file: Path) -> str:
    values = [
        _field_or_none(decision_file, "What remains unknown"),
        _section_or_none(evidence_file, "Missing Evidence"),
    ]
    return _lines_or_none(value for value in values if value != NONE_RECORDED)


def _progress_section_summary(path: Path, heading: str, *, preferred: tuple[str, ...]) -> str:
    section = documents.section(path, heading).content
    rows = _table_rows(section)
    values: list[str] = []
    for row in rows:
        if not any(_meaningful(value) for value in row.values()):
            continue
        label = _first_meaningful(row.get(column, "") for column in preferred)
        if not label:
            label = _first_meaningful(row.values())
        if label:
            values.append(label)
    if values:
        return _bullet_lines(values)

    non_table = _non_table_lines(section)
    return _bullet_lines(non_table) if non_table else NONE_RECORDED


def _field_or_none(path: Path, name: str) -> str:
    value = documents.field(path, name)
    return value if _meaningful(value) else NONE_RECORDED


def _section_or_none(path: Path, heading: str) -> str:
    content = documents.section(path, heading).content
    lines = _non_table_lines(content)
    return _bullet_lines(lines) if lines else NONE_RECORDED


def _lines_or_none(values) -> str:
    lines: list[str] = []
    for value in values:
        for line in str(value).splitlines():
            stripped = line.strip().lstrip("-").strip()
            if _meaningful(stripped):
                lines.append(stripped)
    return _bullet_lines(lines) if lines else NONE_RECORDED


def _bullet_lines(values: list[str]) -> str:
    cleaned: list[str] = []
    for value in values:
        stripped = " ".join(value.strip().split())
        if _meaningful(stripped) and stripped not in cleaned:
            cleaned.append(stripped)
    if not cleaned:
        return NONE_RECORDED
    return "\n".join(f"- {value}" for value in cleaned)


def _non_table_lines(markdown: str) -> list[str]:
    result: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("|") or stripped.startswith("#"):
            continue
        if _meaningful(stripped):
            result.append(stripped.lstrip("-").strip())
    return result


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


def _progress_memory_empty(path: Path) -> bool:
    if not path.is_file():
        return True
    sections = ("Active", "Completed", "Blocked", "Deferred", "Open Questions", "Directions Tried", "Staleness Watch")
    return all(_progress_section_summary(path, section, preferred=("item", "question", "direction", "signal")) == NONE_RECORDED for section in sections)


def _factors_memory_empty(path: Path) -> bool:
    if not path.is_file():
        return True
    text = store.read_text(path)
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if _meaningful(stripped):
            current.append(stripped)
    return not current


def _historical_handoff_exists(session: "Session") -> bool:
    for round_number in range(1, session.state.round + 1):
        round_dir = session.round_dir(round_number)
        decision_file = round_dir / "decision.md"
        evidence_file = round_dir / "evidence.md"
        review_file = round_dir / "review.md"
        if _field_or_none(decision_file, "What remains unknown") != NONE_RECORDED:
            return True
        if _field_or_none(decision_file, "Next smallest step") != NONE_RECORDED:
            return True
        if _section_or_none(evidence_file, "Missing Evidence") != NONE_RECORDED:
            return True
        if documents.field(review_file, "Staleness Signal") in {"possible", "repeated"}:
            return True
    return False


def _all_none(values: tuple[str, ...]) -> bool:
    return all(value == NONE_RECORDED for value in values)


def _first_meaningful(values) -> str:
    for value in values:
        if _meaningful(str(value)):
            return str(value).strip()
    return ""


def _meaningful(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(normalized and normalized not in {"-", "...", "tbd", "todo", "n/a", "not applicable", "none recorded"})

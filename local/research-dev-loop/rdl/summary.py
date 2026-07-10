"""Deterministic top-level session-memory summaries for RDL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import documents, store
from .model import Blocker

if TYPE_CHECKING:
    from .session import Session


SUMMARY_START = "<!-- rdl:summary section={section} start -->"
SUMMARY_END = "<!-- rdl:summary section={section} end -->"
LEDGER_SUMMARY_START = "<!-- rdl:ledger-summary start -->"
LEDGER_SUMMARY_END = "<!-- rdl:ledger-summary end -->"
MAX_TABLE_CELL_CHARS = 240


@dataclass(frozen=True)
class SummaryPlan:
    through_round: int
    rows: dict[str, tuple[str, ...]]
    factor_gaps: tuple[str, ...] = ("factors.md has no deterministic update candidates",)
    blockers: tuple[Blocker, ...] = ()

    @property
    def total_rows(self) -> int:
        return sum(len(rows) for rows in self.rows.values())

    def details(self, status: str) -> dict[str, object]:
        return {
            "summary_status": status,
            "rounds_scanned": self.through_round,
            "progress_updates": {section: len(rows) for section, rows in self.rows.items()},
            "factor_gaps": list(self.factor_gaps),
        }


def plan(session: "Session", through_round: int | None = None) -> SummaryPlan:
    target_round = session.state.round if through_round is None else through_round
    blockers = _round_blockers(session, target_round)
    if blockers:
        return SummaryPlan(target_round, _empty_rows(), blockers=tuple(blockers))

    rows = _empty_rows()
    for round_number in range(1, target_round + 1):
        round_dir = session.round_dir(round_number)
        decision_file = round_dir / "decision.md"
        if not decision_file.is_file():
            continue
        decision = _field(decision_file, "Decision")
        if decision:
            evidence = _field(decision_file, "Evidence") or "none recorded"
            rows["Completed"].append(_row(f"round-{round_number:03d}", decision, evidence, f"{round_number:03d}"))

        for question in _open_question_values(decision_file, round_dir / "evidence.md"):
            rows["Open Questions"].append(_row(question, "unassigned", "unknown", "-"))

        direction = _field(decision_file, "Prior directions checked")
        ruled_out = _field(decision_file, "What this rules out")
        if direction:
            outcome = ruled_out or "recorded"
            rows["Directions Tried"].append(_row(direction, f"{round_number:03d}", outcome, "see decision.md"))

        staleness = documents.field(round_dir / "review.md", "Staleness Signal")
        if staleness in {"possible", "repeated"}:
            response = _field(decision_file, "Stall response") or "record response before repeating direction"
            rows["Staleness Watch"].append(_row(f"{staleness} in round {round_number:03d}", "review.md", response))

    return SummaryPlan(target_round, {section: tuple(_dedupe_rows(section_rows)) for section, section_rows in rows.items()})


def check(session: "Session", through_round: int | None = None) -> SummaryPlan:
    return plan(session, through_round)


def progress_up_to_date(session: "Session", summary_plan: SummaryPlan) -> bool:
    if summary_plan.blockers or summary_plan.total_rows == 0:
        return True
    progress_path = session.root / "progress.md"
    if _progress_write_blockers(progress_path):
        return False
    current = store.read_text(progress_path)
    return _render_progress(current, summary_plan.rows) == current


def write(session: "Session", summary_plan: SummaryPlan) -> tuple[Blocker, ...]:
    if summary_plan.blockers:
        return summary_plan.blockers
    progress_path = session.root / "progress.md"
    blockers = _progress_write_blockers(progress_path)
    if blockers:
        return tuple(blockers)

    current = store.read_text(progress_path)
    rendered = _render_progress(current, summary_plan.rows)
    if rendered != current:
        store.write_text_atomic(progress_path, rendered)

    _write_ledger_summary(session.root / "decision-ledger.md", summary_plan)
    return ()


def _empty_rows() -> dict[str, list[str]]:
    return {
        "Completed": [],
        "Open Questions": [],
        "Directions Tried": [],
        "Staleness Watch": [],
    }


def _round_blockers(session: "Session", through_round: int) -> list[Blocker]:
    if through_round < 1:
        return [
            Blocker(
                "invalid_summary_round",
                "",
                "summary round must be at least 1.",
                "Pass --round between 1 and the current session round.",
            )
        ]
    if through_round > session.state.round:
        return [
            Blocker(
                "invalid_summary_round",
                "",
                "summary round cannot exceed the current session round.",
                "Pass --round between 1 and the current session round.",
            )
        ]
    return []


def _progress_write_blockers(path: Path) -> list[Blocker]:
    blockers: list[Blocker] = []
    expected_headers = {
        "Completed": "| Item | Decision | Evidence | Round |",
        "Open Questions": "| Question | Owner | Blocking? | Resolution |",
        "Directions Tried": "| Direction | Rounds | Outcome | Why Not Repeat |",
        "Staleness Watch": "| Signal | Evidence | Response |",
    }
    for section, header in expected_headers.items():
        parsed = documents.section(path, section)
        if parsed.start_line is None:
            blockers.append(
                Blocker(
                    "missing_progress_section",
                    f"progress.md#{section}",
                    f"{section} section is missing.",
                    f"Restore the {section} section in progress.md.",
                )
            )
        elif header not in parsed.content:
            blockers.append(
                Blocker(
                    "unsupported_progress_table",
                    f"progress.md#{section}",
                    f"{section} table header is not the canonical RDL header.",
                    "Restore the canonical progress.md table before writing a summary.",
                )
            )
    return blockers


def _render_progress(text: str, rows: dict[str, tuple[str, ...]]) -> str:
    result = text
    for section, section_rows in rows.items():
        result = _replace_section_block(result, section, section_rows)
    return result if result.endswith("\n") else result + "\n"


def _replace_section_block(text: str, section: str, rows: tuple[str, ...]) -> str:
    start = SUMMARY_START.format(section=section)
    end = SUMMARY_END.format(section=section)
    block = "\n".join((start, *rows, end))
    pattern = re.compile(
        rf"\n?{re.escape(start)}\n(?:.*?\n)?{re.escape(end)}",
        re.DOTALL,
    )
    if pattern.search(text):
        return pattern.sub("\n" + block, text)

    heading_match = re.search(rf"^## {re.escape(section)}[ \t]*$", text, re.MULTILINE)
    if heading_match is None:
        return text
    next_heading = re.search(r"^## [^\n]+$", text[heading_match.end() :], re.MULTILINE)
    insert_at = len(text) if next_heading is None else heading_match.end() + next_heading.start()
    prefix = text[:insert_at].rstrip()
    suffix = text[insert_at:].lstrip("\n")
    return f"{prefix}\n\n{block}\n\n{suffix}"


def _write_ledger_summary(path: Path, summary_plan: SummaryPlan) -> None:
    current = store.read_text(path)
    rendered = _render_ledger_summary(current, summary_plan)
    if rendered != current:
        store.write_text_atomic(path, rendered)


def _render_ledger_summary(text: str, summary_plan: SummaryPlan) -> str:
    updates = summary_plan.details("written")["progress_updates"]
    block = "\n".join(
        (
            LEDGER_SUMMARY_START,
            "## Session Summary Refresh",
            "",
            f"- Through round: {summary_plan.through_round:03d}",
            f"- Completed rows generated: {updates['Completed']}",
            f"- Open question rows generated: {updates['Open Questions']}",
            f"- Directions tried rows generated: {updates['Directions Tried']}",
            f"- Staleness watch rows generated: {updates['Staleness Watch']}",
            "- Factors updated: no deterministic candidates",
            LEDGER_SUMMARY_END,
        )
    )
    pattern = re.compile(
        rf"\n?{re.escape(LEDGER_SUMMARY_START)}\n.*?\n{re.escape(LEDGER_SUMMARY_END)}",
        re.DOTALL,
    )
    if pattern.search(text):
        rendered = pattern.sub("\n" + block, text)
        return rendered if rendered.endswith("\n") else rendered + "\n"
    base = text.rstrip()
    return (
        f"{base}\n\n{block}\n"
        if base
        else f"{block}\n"
    )

def _open_question_values(decision_file: Path, evidence_file: Path) -> list[str]:
    values: list[str] = []
    unknown = _field(decision_file, "What remains unknown")
    if unknown:
        values.append(unknown)
    missing = documents.section(evidence_file, "Missing Evidence").content
    values.extend(_content_lines(missing))
    return _dedupe(values)


def _field(path: Path, name: str) -> str:
    value = documents.field_text(path, name)
    return value if _meaningful(value) else ""


def _content_lines(text: str) -> list[str]:
    values: list[str] = []
    paragraph: list[str] = []
    bullet_paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            values.append(" ".join(paragraph))
            paragraph.clear()

    def flush_bullet() -> None:
        if bullet_paragraph:
            values.append(" ".join(bullet_paragraph))
            bullet_paragraph.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            flush_bullet()
            flush_paragraph()
            continue
        if stripped.startswith("|") or _managed_comment(stripped):
            flush_bullet()
            flush_paragraph()
            continue
        bullet = stripped.startswith(("-", "*"))
        cleaned = stripped.lstrip("-*").strip()
        if not _meaningful(cleaned):
            continue
        if bullet:
            flush_bullet()
            flush_paragraph()
            bullet_paragraph.append(cleaned)
        elif bullet_paragraph and line[:1].isspace():
            bullet_paragraph.append(cleaned)
        else:
            flush_bullet()
            paragraph.append(cleaned)
    flush_bullet()
    flush_paragraph()
    return values


def _dedupe(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_cell(str(value))
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _dedupe_rows(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value).strip().split())
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _clean_cell(value: str) -> str:
    return _cell(value)


def _row(*cells: str) -> str:
    return "| " + " | ".join(_cell(cell) for cell in cells) + " |"


def _cell(value: str) -> str:
    compact = " ".join(str(value).replace("|", "/").strip().split())
    if len(compact) > MAX_TABLE_CELL_CHARS:
        return compact[: MAX_TABLE_CELL_CHARS - 3].rstrip() + "..."
    return compact


def _managed_comment(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith("<!--") and stripped.endswith("-->")


def _meaningful(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"-", "...", "tbd", "todo", "n/a", "not applicable", "none", "none recorded"}:
        return False
    if normalized.startswith("no blocking missing evidence") or normalized.startswith("no missing evidence"):
        return False
    return bool(normalized)

"""Explicit editors for top-level RDL session memory files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import documents, store
from .model import Blocker


PROGRESS_MANUAL_SECTIONS = ("Active", "Blocked", "Deferred")

PROGRESS_HEADERS = {
    "Active": "| Item | Mode | Claim or Capability | Blocking? | Next Review Trigger |",
    "Blocked": "| Item | Reason | Needed Evidence or Input | Decision Impact |",
    "Deferred": "| Item | Reason | Revisit Trigger |",
}

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
class EditResult:
    updated_file: str
    updated_section: str
    row_added: bool = False
    write_mode: str = ""

    def details(self) -> dict[str, object]:
        result: dict[str, object] = {
            "updated_file": self.updated_file,
            "updated_section": self.updated_section,
        }
        if self.row_added:
            result["row_added"] = True
        if self.write_mode:
            result["write_mode"] = self.write_mode
        return result


def append_progress_row(session_root: Path, section: str, cells: tuple[str, ...]) -> tuple[EditResult | None, tuple[Blocker, ...]]:
    progress_path = session_root / "progress.md"
    blockers = _progress_section_blockers(progress_path, section)
    if blockers:
        return None, tuple(blockers)

    row = "| " + " | ".join(_clean_cell(cell) for cell in cells) + " |"
    text = store.read_text(progress_path)
    rendered = _insert_before_next_heading(text, section, row)
    store.write_text_atomic(progress_path, rendered)
    return EditResult("progress.md", section, row_added=True), ()


def set_factor(session_root: Path, section: str, value: str) -> tuple[EditResult | None, tuple[Blocker, ...]]:
    factors_path = session_root / "factors.md"
    blockers = _factor_section_blockers(factors_path, section)
    if blockers:
        return None, tuple(blockers)

    rendered = _replace_section_content(store.read_text(factors_path), section, _clean_text(value))
    store.write_text_atomic(factors_path, rendered)
    return EditResult("factors.md", section, write_mode="set"), ()


def append_factor_note(session_root: Path, section: str, value: str) -> tuple[EditResult | None, tuple[Blocker, ...]]:
    factors_path = session_root / "factors.md"
    blockers = _factor_section_blockers(factors_path, section)
    if blockers:
        return None, tuple(blockers)

    rendered = _insert_before_next_heading(store.read_text(factors_path), section, f"- {_clean_text(value)}")
    store.write_text_atomic(factors_path, rendered)
    return EditResult("factors.md", section, write_mode="note"), ()


def value_blocker(value: str | None, option: str) -> Blocker | None:
    if value is None or not _meaningful(value):
        return Blocker(
            "missing_memory_value",
            "",
            f"{option} requires a non-placeholder value.",
            f"Pass a concrete value for {option}.",
        )
    return None


def _progress_section_blockers(path: Path, section: str) -> list[Blocker]:
    if section not in PROGRESS_MANUAL_SECTIONS:
        return [
            Blocker(
                "invalid_progress_section",
                "",
                "progress section must be Active, Blocked, or Deferred.",
                "Use Active, Blocked, or Deferred.",
            )
        ]
    parsed = documents.section(path, section)
    if parsed.start_line is None:
        return [
            Blocker(
                "missing_progress_section",
                f"progress.md#{section}",
                f"{section} section is missing.",
                f"Restore the {section} section in progress.md.",
            )
        ]
    if PROGRESS_HEADERS[section] not in parsed.content:
        return [
            Blocker(
                "unsupported_progress_table",
                f"progress.md#{section}",
                f"{section} table header is not the canonical RDL header.",
                "Restore the canonical progress.md table before writing session memory.",
            )
        ]
    return []


def _factor_section_blockers(path: Path, section: str) -> list[Blocker]:
    if section not in FACTOR_SECTIONS:
        return [
            Blocker(
                "invalid_factor_section",
                "",
                "factor section is not a canonical RDL factor heading.",
                "Use one of the canonical factors.md section headings.",
            )
        ]
    parsed = documents.section(path, section)
    if parsed.start_line is None:
        return [
            Blocker(
                "missing_factor_section",
                f"factors.md#{section}",
                f"{section} section is missing.",
                f"Restore the {section} section in factors.md.",
            )
        ]
    return []


def _insert_before_next_heading(text: str, section: str, line_to_insert: str) -> str:
    lines = text.splitlines()
    start, end = _section_bounds(lines, section)
    insert_at = end
    while insert_at > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, line_to_insert)
    return "\n".join(lines).rstrip() + "\n"


def _replace_section_content(text: str, section: str, content: str) -> str:
    lines = text.splitlines()
    start, end = _section_bounds(lines, section)
    replacement = [""]
    replacement.extend(content.splitlines())
    replacement.append("")
    lines[start:end] = replacement
    return "\n".join(lines).rstrip() + "\n"


def _section_bounds(lines: list[str], section: str) -> tuple[int, int]:
    heading_re = re.compile(rf"^[ \t]*##[ \t]+{re.escape(section)}[ \t]*$")
    start = None
    for index, line in enumerate(lines):
        if heading_re.match(line):
            start = index + 1
            break
    if start is None:
        raise ValueError(f"missing section: {section}")
    end = len(lines)
    for index in range(start, len(lines)):
        if re.match(r"^[ \t]*##[ \t]+", lines[index]):
            end = index
            break
    return start, end


def _clean_cell(value: str) -> str:
    return _clean_text(value).replace("|", "/")


def _clean_text(value: str) -> str:
    return " ".join(value.strip().split())


def _meaningful(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(normalized and normalized not in {"-", "...", "tbd", "todo", "n/a", "not applicable", "none recorded"})

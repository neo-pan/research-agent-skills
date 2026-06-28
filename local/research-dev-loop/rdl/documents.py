"""Markdown parsing and document-level validation for RDL."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .model import Blocker
from .protocol import descriptor


@dataclass(frozen=True)
class MarkdownSection:
    heading: str
    content: str
    start_line: int | None = None
    end_line: int | None = None


def field(path: str | Path, name: str) -> str:
    for line in _read_lines(path):
        match = re.match(rf"^[ \t]*{re.escape(name)}:[ \t]*(.*)$", line)
        if match:
            return match.group(1).strip()
    return ""


def section(path: str | Path, heading: str) -> MarkdownSection:
    lines = _read_lines(path)
    start_index: int | None = None
    end_index: int | None = None
    heading_re = re.compile(rf"^[ \t]*##[ \t]+{re.escape(heading)}[ \t]*$")

    for index, line in enumerate(lines):
        if start_index is None:
            if heading_re.match(line):
                start_index = index + 1
            continue
        if re.match(r"^[ \t]*##[ \t]+", line):
            end_index = index
            break

    if start_index is None:
        return MarkdownSection(heading=heading, content="")

    if end_index is None:
        end_index = len(lines)

    content = "\n".join(lines[start_index:end_index]).strip("\n")
    return MarkdownSection(
        heading=heading,
        content=content,
        start_line=start_index + 1,
        end_line=end_index,
    )


def has_content(path: str | Path) -> bool:
    return _text_has_content("\n".join(_read_lines(path)), ignore_checklist=True)


def section_has_content(path: str | Path, heading: str) -> bool:
    return _text_has_content(section(path, heading).content, ignore_checklist=False)


def extract_artifact_ids(markdown_text: str) -> set[str]:
    return set(re.findall(r"\b[A-Z][A-Z0-9]*-?[0-9][A-Z0-9-]*\b", markdown_text.replace("`", "")))


def validate(kind: str, path: str | Path, context: dict[str, Any] | None = None) -> list[Blocker]:
    context = context or {}
    if kind == "review":
        return _validate_review(Path(path))
    if kind == "decision":
        return _validate_decision(Path(path), context)
    if kind == "final-report":
        return _validate_final_report(Path(path), context)
    if kind == "progress":
        return _validate_progress(Path(path))
    return []


def _validate_review(path: Path) -> list[Blocker]:
    if not path.is_file():
        return [
            Blocker(
                "missing_review",
                str(path),
                "review.md is missing.",
                "Run rdl review and complete the review record.",
            )
        ]

    blockers: list[Blocker] = []
    for required_field in descriptor.required_fields("review"):
        value = field(path, required_field)
        if _placeholder(value) or "|" in value:
            blockers.append(
                Blocker(
                    "missing_review_field",
                    f"{path}#{required_field}",
                    f"{required_field} is missing or still a placeholder.",
                    f"Complete {required_field} in review.md.",
                )
            )

    review_mode = field(path, "Review Mode")
    if not descriptor.value_allowed("review-mode", review_mode):
        blockers.append(
            Blocker(
                "invalid_review_mode",
                f"{path}#Review Mode",
                "Review Mode is unsupported.",
                "Use manual, checklist, phase-review, subagent, or project-adapter.",
            )
        )

    verdict = field(path, "Verdict")
    if not descriptor.value_allowed("review-verdict", verdict):
        blockers.append(
            Blocker(
                "invalid_review_verdict",
                f"{path}#Verdict",
                "Verdict is unsupported.",
                "Use PASS, PASS_WITH_NOTES, BLOCKED, or INCONCLUSIVE.",
            )
        )
    return blockers


def _validate_decision(path: Path, context: dict[str, Any]) -> list[Blocker]:
    if not path.is_file():
        return [
            Blocker(
                "missing_decision",
                str(path),
                "decision.md is missing.",
                "Run rdl decide <decision-type> and complete the decision record.",
            )
        ]

    blockers: list[Blocker] = []
    for required_field in descriptor.required_fields("decision"):
        value = field(path, required_field)
        if _placeholder(value) or "|" in value:
            blockers.append(
                Blocker(
                    "missing_decision_field",
                    f"{path}#{required_field}",
                    f"{required_field} is missing or still a placeholder.",
                    f"Complete {required_field} in decision.md.",
                )
            )

    decision = field(path, "Decision")
    if not descriptor.value_allowed("decision-type", decision):
        blockers.append(
            Blocker(
                "invalid_decision_type",
                f"{path}#Decision",
                "Decision type is unsupported.",
                "Use a planned RDL decision type.",
            )
        )

    expected_closes = context.get("expected_closes")
    closes = field(path, "Closes")
    if expected_closes and closes != expected_closes:
        blockers.append(
            Blocker(
                "invalid_closes",
                f"{path}#Closes",
                f"Closes must be {expected_closes} for this session mode.",
                f"Set Closes: {expected_closes}.",
            )
        )

    next_loop = field(path, "Recommended next loop")
    if not descriptor.value_allowed("recommended-next-loop", next_loop):
        blockers.append(
            Blocker(
                "invalid_recommended_next_loop",
                f"{path}#Recommended next loop",
                "Recommended next loop is unsupported.",
                "Use research, build, or none.",
            )
        )
    return blockers


def _validate_final_report(path: Path, context: dict[str, Any]) -> list[Blocker]:
    if not path.is_file():
        return [
            Blocker(
                "missing_final_report",
                str(path),
                "final-report.md is required before closing a session.",
                "Create final-report.md from the template and complete the close record.",
            )
        ]

    blockers: list[Blocker] = []
    for required_section in descriptor.required_sections("final-report"):
        if not section_has_content(path, required_section):
            blockers.append(
                Blocker(
                    "missing_final_report_section",
                    f"{path}#{required_section}",
                    f"{required_section} is missing or still a placeholder.",
                    f"Complete {required_section} in final-report.md.",
                )
            )

    if re.search(r"^[ \t]*-[ \t]*\[[ \t]\]", path.read_text(encoding="utf-8"), re.MULTILINE):
        blockers.append(
            Blocker(
                "incomplete_close_checklist",
                f"{path}#Close Checklist",
                "Close checklist still has unchecked items.",
                "Check every close checklist item that is true for this close record.",
            )
        )

    expected_outcome = context.get("outcome")
    if expected_outcome:
        recorded = _first_meaningful_line(section(path, "Outcome").content).lower()
        if recorded in {"positive", "negative", "inconclusive"}:
            recorded = f"closed-{recorded}"
        if recorded != f"closed-{expected_outcome}":
            blockers.append(
                Blocker(
                    "close_outcome_mismatch",
                    f"{path}#Outcome",
                    f"Final report outcome must match {expected_outcome}.",
                    "Update final-report.md Outcome or run rdl close with the recorded outcome.",
                )
            )
    return blockers


def _validate_progress(path: Path) -> list[Blocker]:
    if not path.is_file():
        return [
            Blocker(
                "missing_progress",
                str(path),
                "progress.md is missing.",
                "Restore progress.md.",
            )
        ]

    blockers: list[Blocker] = []
    for required_section in descriptor.required_sections("progress"):
        if section(path, required_section).start_line is None:
            blockers.append(
                Blocker(
                    "missing_progress_section",
                    f"{path}#{required_section}",
                    f"{required_section} section is missing.",
                    f"Restore the {required_section} section in progress.md.",
                )
            )
    return blockers


def _read_lines(path: str | Path) -> list[str]:
    candidate = Path(path)
    if not candidate.is_file():
        return []
    return candidate.read_text(encoding="utf-8").splitlines()


def _placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"", "-", "...", "tbd", "todo", "n/a"}


def _text_has_content(text: str, *, ignore_checklist: bool) -> bool:
    pending_table_row = ""
    for line in text.splitlines():
        if _is_table_row(line):
            if _is_table_separator(line):
                pending_table_row = ""
                continue
            if pending_table_row and _meaningful_table_row(pending_table_row):
                return True
            pending_table_row = line
            continue

        if pending_table_row and _meaningful_table_row(pending_table_row):
            return True
        pending_table_row = ""

        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("<!--"):
            continue
        if ignore_checklist and re.match(r"^-\s*\[[ xX]\]", stripped):
            continue
        if _strength_option_line(stripped):
            continue
        if not _placeholder(stripped) and re.search(r"[A-Za-z0-9]", stripped):
            return True

    return bool(pending_table_row and _meaningful_table_row(pending_table_row))


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _is_table_separator(line: str) -> bool:
    return bool(re.match(r"^[ \t]*\|[ \t:|-]+\|[ \t|:-]*$", line))


def _meaningful_table_row(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    meaningful_cells = [
        cell
        for cell in cells
        if cell.lower() not in {"", "-", "...", "tbd", "todo", "n/a"}
        and re.search(r"[A-Za-z0-9]", cell)
    ]
    return bool(meaningful_cells)


def _strength_option_line(value: str) -> bool:
    return bool(
        re.fullmatch(
            r"(Strong|Moderate|Weak|Contradicted|Inconclusive)"
            r"(\s*\|\s*(Strong|Moderate|Weak|Contradicted|Inconclusive))*",
            value,
        )
    )


def _first_meaningful_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("<!--"):
            return stripped
    return ""

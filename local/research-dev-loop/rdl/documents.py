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


def field_text(path: str | Path, name: str) -> str:
    """Return a field value plus following continuation lines.

    `field()` intentionally stays single-line for enum-like protocol fields.
    Use this helper for free-text fields such as Evidence or What remains
    unknown, where wrapping the value across lines must not truncate handoff
    state.
    """

    lines = _read_lines(path)
    for index, line in enumerate(lines):
        match = re.match(rf"^[ \t]*{re.escape(name)}:[ \t]*(.*)$", line)
        if not match:
            continue
        values = [match.group(1).strip()]
        for continuation in lines[index + 1 :]:
            stripped = continuation.strip()
            if not stripped or stripped.startswith("#") or _field_like_line(stripped):
                break
            values.append(stripped)
        return "\n".join(value for value in values if value).strip()
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
    return _text_has_content("\n".join(_read_lines(path)))


def section_has_content(path: str | Path, heading: str) -> bool:
    return _text_has_content(section(path, heading).content)


def extract_artifact_ids(markdown_text: str) -> set[str]:
    return set(re.findall(r"\[artifact:([A-Za-z][A-Za-z0-9_.-]*)\]", markdown_text))


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

    spec = descriptor.document_spec("review")
    blockers: list[Blocker] = []
    for required_field in spec.required_fields if spec is not None else ():
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
    if spec is None or review_mode not in spec.values_for_field("Review Mode"):
        blockers.append(
            Blocker(
                "invalid_review_mode",
                f"{path}#Review Mode",
                "Review Mode is unsupported.",
                "Use manual, checklist, phase-review, subagent, or project-adapter.",
            )
        )

    verdict = field(path, "Verdict")
    if spec is None or verdict not in spec.values_for_field("Verdict"):
        blockers.append(
            Blocker(
                "invalid_review_verdict",
                f"{path}#Verdict",
                "Verdict is unsupported.",
                "Use PASS, PASS_WITH_NOTES, BLOCKED, or INCONCLUSIVE.",
            )
        )
    fresh_evidence = field(path, "Fresh Evidence")
    if spec is None or fresh_evidence not in spec.values_for_field("Fresh Evidence"):
        blockers.append(
            Blocker(
                "invalid_fresh_evidence",
                f"{path}#Fresh Evidence",
                "Fresh Evidence is unsupported.",
                "Use yes, mixed, or no.",
            )
        )
    staleness_signal = field(path, "Staleness Signal")
    if spec is None or staleness_signal not in spec.values_for_field("Staleness Signal"):
        blockers.append(
            Blocker(
                "invalid_staleness_signal",
                f"{path}#Staleness Signal",
                "Staleness Signal is unsupported.",
                "Use none, possible, or repeated.",
            )
        )
    direction_reuse_risk = field(path, "Direction Reuse Risk")
    if spec is None or direction_reuse_risk not in spec.values_for_field("Direction Reuse Risk"):
        blockers.append(
            Blocker(
                "invalid_direction_reuse_risk",
                f"{path}#Direction Reuse Risk",
                "Direction Reuse Risk is unsupported.",
                "Use low, medium, or high.",
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

    spec = descriptor.document_spec("decision")
    blockers: list[Blocker] = []
    for required_field in spec.required_fields if spec is not None else ():
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
    if spec is None or decision not in spec.values_for_field("Decision"):
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
    if spec is None or next_loop not in spec.values_for_field("Recommended next loop"):
        blockers.append(
            Blocker(
                "invalid_recommended_next_loop",
                f"{path}#Recommended next loop",
                "Recommended next loop is unsupported.",
                "Use research, build, or none.",
            )
        )
    direction_changed = field(path, "Direction changed")
    if spec is None or direction_changed not in spec.values_for_field("Direction changed"):
        blockers.append(
            Blocker(
                "invalid_direction_changed",
                f"{path}#Direction changed",
                "Direction changed is unsupported.",
                "Use yes, no, or closing.",
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

    spec = descriptor.document_spec("final-report")
    blockers: list[Blocker] = []
    for required_section in spec.required_sections if spec is not None else ():
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

    spec = descriptor.document_spec("progress")
    blockers: list[Blocker] = []
    for required_section in spec.required_sections if spec is not None else ():
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


def _field_like_line(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9 /?()_-]{0,80}:[ \t]*", value))


def _placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in {"", "-", "...", "tbd", "todo", "n/a"}


def _text_has_content(text: str) -> bool:
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
        if re.match(r"^-\s*\[[ \t]\]", stripped):
            continue
        if re.match(r"^-\s*\[[xX]\]", stripped):
            return True
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

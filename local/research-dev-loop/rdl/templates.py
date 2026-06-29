"""Template lookup and rendering for Python RDL commands."""

from __future__ import annotations

from pathlib import Path

from . import store
from .model import SessionMode


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


def template_path(name: str) -> Path:
    path = TEMPLATE_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"RDL template not found: {name}")
    return path


def copy_template(name: str, destination: str | Path) -> None:
    store.copy_file(template_path(name), destination)


def render_prompt(mode: SessionMode | str, round_number: int, objective: str, previous_decision: str) -> str:
    mode_value = mode.value if isinstance(mode, SessionMode) else str(mode)
    if mode_value == SessionMode.RESEARCH.value:
        required_files = "prompt.md, evidence.md, interpretation.md, review.md, decision.md"
        expected_exit_decision = "claim decision with evidence and uncertainty"
    elif mode_value == SessionMode.BUILD.value:
        required_files = "prompt.md, intent.md, work.md, evidence.md, review.md, decision.md"
        expected_exit_decision = "capability decision with verification evidence"
    else:
        raise ValueError("mode must be research or build")

    replacements = {
        "{{MODE}}": mode_value,
        "{{ROUND}}": str(round_number),
        "{{OBJECTIVE}}": objective,
        "{{PREVIOUS_DECISION}}": previous_decision,
        "{{REQUIRED_FILES}}": required_files,
        "{{EXPECTED_EXIT_DECISION}}": expected_exit_decision,
    }
    text = store.read_text(template_path("prompt.md"))
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text


def write_prompt(
    destination: str | Path,
    mode: SessionMode | str,
    round_number: int,
    objective: str,
    previous_decision: str,
) -> None:
    store.write_text_atomic(destination, render_prompt(mode, round_number, objective, previous_decision))

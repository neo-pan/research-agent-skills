"""Template lookup and rendering for Python RDL commands."""

from __future__ import annotations

from pathlib import Path

from . import store
from .model import SessionMode
from .protocol import descriptor


TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"


def template_path(name: str) -> Path:
    path = TEMPLATE_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"RDL template not found: {name}")
    return path


def copy_template(name: str, destination: str | Path) -> None:
    store.copy_file(template_path(name), destination)


def render_decision(decision_type: str, closes: str) -> str:
    text = store.read_text(template_path("decision.md"))
    replacements = {
        "Decision:": f"Decision: {decision_type}",
        "Closes: claim | capability": f"Closes: {closes}",
    }
    for marker, value in replacements.items():
        text = text.replace(marker, value, 1)
    return text


def write_decision(destination: str | Path, decision_type: str, closes: str) -> None:
    store.write_text_atomic(destination, render_decision(decision_type, closes))


def render_prompt(mode: SessionMode | str, round_number: int, objective: str, previous_decision: str) -> str:
    mode_value = mode.value if isinstance(mode, SessionMode) else str(mode)
    required_files = descriptor.completed_round_files(mode_value)
    expected_exit_decision = descriptor.prompt_expected_exit_decision(mode_value)
    if not required_files or not expected_exit_decision:
        raise ValueError("mode must be research or build")

    replacements = {
        "{{MODE}}": mode_value,
        "{{ROUND}}": str(round_number),
        "{{OBJECTIVE}}": objective,
        "{{PREVIOUS_DECISION}}": previous_decision,
        "{{REQUIRED_FILES}}": ", ".join(required_files),
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

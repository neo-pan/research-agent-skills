"""Session state transitions for RDL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import documents, memory, store, templates
from .model import Blocker, CloseOutcome, SessionPhase, SessionStatus
from .protocol import descriptor


LEDGER_CLOSE_START = "<!-- rdl:transition kind=close start -->"
LEDGER_CLOSE_END = "<!-- rdl:transition kind=close end -->"
CLOSE_RECORD_FORMAT = "rdl-close-v2"


@dataclass(frozen=True)
class TransitionResult:
    phase: str
    round: int
    next_action: str
    mode: str = ""
    profile: str = ""


class TransitionBlocked(Exception):
    def __init__(self, blocker: Blocker):
        super().__init__(blocker.message)
        self.blocker = blocker


def advance(session: Any, next_mode: str | None = None, next_profile: str | None = None) -> TransitionResult:
    state = session.state
    current_round = state.round
    next_round = current_round + 1
    target_mode = next_mode or str(state.mode)
    target_profile = next_profile or str(state.profile)
    if descriptor.mode_spec(target_mode) is None:
        raise TransitionBlocked(
            Blocker(
                "invalid_mode",
                "",
                "mode must be research or build.",
                "Use research or build for the next round mode.",
            )
        )
    if descriptor.profile_spec(target_profile) is None:
        raise TransitionBlocked(
            Blocker(
                "invalid_profile",
                "",
                "profile must be full-review, checkpoint, or build-update.",
                "Use full-review, checkpoint, or build-update for the next round profile.",
            )
        )
    if not descriptor.profile_allowed_for_mode(target_mode, target_profile):
        raise TransitionBlocked(
            Blocker(
                "invalid_profile_for_mode",
                "",
                "profile is not supported for the selected mode.",
                "Use full-review or checkpoint for research; use any supported profile for build.",
            )
        )
    next_round_dir = session.round_dir(next_round)
    relative_next_round = f"rounds/{next_round:03d}"
    if next_round_dir.exists():
        raise TransitionBlocked(
            Blocker(
                "next_round_exists",
                relative_next_round,
                "Next round directory already exists.",
                "Inspect the existing next round before advancing.",
            )
        )

    decision_file = session.round_dir(current_round) / "decision.md"
    decision = documents.field(decision_file, "Decision")
    next_loop = documents.field(decision_file, "Recommended next loop")
    expected_closes = descriptor.expected_closes(state.mode)
    previous_decision = f"{decision}; closes {expected_closes}; recommended next loop {next_loop}"
    prompt_context = memory.prompt_context(session, current_round)

    next_round_dir.mkdir(parents=True)
    prompt_path = next_round_dir / "prompt.md"
    templates.write_prompt(
        prompt_path,
        target_mode,
        target_profile,
        next_round,
        f"Continue {target_mode} session {state.session_id}",
        previous_decision,
        prompt_context,
    )

    now = now_utc()
    _update_state(
        session.root,
        {
            "round": next_round,
            "mode": target_mode,
            "profile": target_profile,
            "phase": SessionPhase.PLAN.value,
            "updated_at_utc": now,
        },
    )
    _append_round_decision(
        session.root,
        current_round,
        str(state.profile),
        decision,
        expected_closes,
        next_loop,
        next_round,
        target_mode,
        target_profile,
    )
    return TransitionResult(SessionPhase.PLAN.value, next_round, str(prompt_path), target_mode, target_profile)


def close(session: Any, outcome: CloseOutcome | str) -> TransitionResult:
    outcome_value = outcome.value if isinstance(outcome, CloseOutcome) else str(outcome)
    status = f"closed-{outcome_value}"
    now = now_utc()
    _mark_session_ended(session.root, status, now)
    _append_close_record(session.root, outcome_value, descriptor.expected_closes(session.state.mode), session.state.round, now)
    return TransitionResult(SessionPhase.COMPLETE.value, session.state.round, status)


def abandon(session: Any, reason: str) -> TransitionResult:
    now = now_utc()
    _mark_session_ended(session.root, SessionStatus.ABANDONED.value, now)
    _append_abandon_records(session.root, reason, session.state.round, now)
    return TransitionResult(SessionPhase.COMPLETE.value, session.state.round, SessionStatus.ABANDONED.value)


def from_decision(session: Any) -> TransitionResult:
    decision = documents.field(session.round_dir() / "decision.md", "Decision")
    if decision == "close-positive":
        return close(session, CloseOutcome.POSITIVE)
    if decision == "close-negative":
        return close(session, CloseOutcome.NEGATIVE)
    if decision == "close-inconclusive":
        return close(session, CloseOutcome.INCONCLUSIVE)
    return advance(session)


def mark_guard_seen(session: Any, guard_session_id: str | None, guard_command_id: str | None) -> None:
    updates: dict[str, object] = {}
    if session.state.status == SessionStatus.ACTIVE:
        updates["updated_at_utc"] = now_utc()
    if guard_session_id:
        updates["guard_session_id"] = guard_session_id
    if guard_command_id:
        updates["last_guard_command_id"] = guard_command_id
    _update_state(session.root, updates)


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _mark_session_ended(session_dir: Path, status: str, now: str) -> None:
    _update_state(
        session_dir,
        {
            "status": status,
            "phase": SessionPhase.COMPLETE.value,
            "updated_at_utc": now,
        },
    )


def _update_state(session_dir: Path, updates: dict[str, object]) -> None:
    state_path = session_dir / "state.json"
    data = store.read_json(state_path)
    if not isinstance(data, dict):
        raise ValueError("state.json must contain a JSON object")
    data.update(updates)
    store.write_json_atomic(state_path, data)


def _append_round_decision(
    session_dir: Path,
    round_number: int,
    current_profile: str,
    decision: str,
    expected_closes: str,
    next_loop: str,
    next_round: int,
    next_mode: str,
    next_profile: str,
) -> None:
    _append_text(
        session_dir / "decision-ledger.md",
        "\n"
        f"## Round {round_number} Decision\n\n"
        f"- Profile: {current_profile}\n"
        f"- Decision: {decision}\n"
        f"- Closes: {expected_closes}\n"
        f"- Recommended next loop: {next_loop}\n"
        f"- Next round: {next_round:03d}\n"
        f"- Next mode: {next_mode}\n"
        f"- Next profile: {next_profile}\n"
        + _decision_summary(session_dir / "rounds" / f"{round_number:03d}" / "decision.md")
    )


def _append_close_record(session_dir: Path, outcome: str, expected_closes: str, round_number: int, now: str) -> None:
    record = _render_close_record(session_dir, outcome, expected_closes, round_number, now)
    _append_text(session_dir / "decision-ledger.md", record)


def without_generated_close_record(session: Any, text: str) -> str:
    outcomes = {
        SessionStatus.CLOSED_POSITIVE: CloseOutcome.POSITIVE.value,
        SessionStatus.CLOSED_NEGATIVE: CloseOutcome.NEGATIVE.value,
        SessionStatus.CLOSED_INCONCLUSIVE: CloseOutcome.INCONCLUSIVE.value,
    }
    outcome = outcomes.get(session.state.status)
    if outcome is None:
        return text
    decision_file = session.round_dir() / "decision.md"
    if documents.field(decision_file, "Decision") != f"close-{outcome}":
        return text
    legacy = _close_record_is_legacy(session)
    if legacy is None:
        return text
    variant = _render_close_record(
        session.root,
        outcome,
        descriptor.expected_closes(session.state.mode),
        session.state.round,
        session.state.updated_at_utc,
        legacy=legacy,
    )
    candidate = text.rstrip("\n")
    suffix = variant.rstrip("\n")
    if candidate.endswith(suffix):
        return candidate[: -len(suffix)].rstrip() + "\n\n"
    return text


def _close_record_is_legacy(session: Any) -> bool | None:
    try:
        report = store.read_json(session.round_dir() / "gate-report.json")
    except (OSError, ValueError):
        return None
    if not isinstance(report, dict):
        return None
    expected = {
        "schema_version": 1,
        "session_id": session.state.session_id,
        "round": session.state.round,
        "mode": str(session.state.mode),
        "profile": str(session.state.profile),
        "action": "close",
    }
    if any(report.get(key) != value for key, value in expected.items()):
        return None
    if report.get("status") not in {"ok", "needs_attention"}:
        return None
    if not isinstance(report.get("warnings"), list) or report.get("blockers") != []:
        return None
    if not isinstance(report.get("details"), dict):
        return None
    if "close_record_format" not in report:
        return True
    if report["close_record_format"] == CLOSE_RECORD_FORMAT:
        return False
    return None


def _render_close_record(
    session_dir: Path,
    outcome: str,
    expected_closes: str,
    round_number: int,
    now: str,
    *,
    legacy: bool = False,
) -> str:
    decision_file = session_dir / "rounds" / f"{round_number:03d}" / "decision.md"
    summary_text = (
        _decision_summary(decision_file)
        if legacy
        else _close_decision_summary(decision_file, f"closed-{outcome}")
    )
    marker_start = "" if legacy else f"{LEDGER_CLOSE_START}\n"
    marker_end = "" if legacy else f"{LEDGER_CLOSE_END}\n"
    format_line = "" if legacy else f"- Record Format: {CLOSE_RECORD_FORMAT}\n"
    return (
        "\n"
        f"{marker_start}"
        "## Session Closed\n\n"
        f"{format_line}"
        f"- Outcome: {outcome}\n"
        f"- Decision: close-{outcome}\n"
        f"- Closes: {expected_closes}\n"
        f"- Round: {round_number:03d}\n"
        f"- Closed at UTC: {now}\n"
        f"{summary_text}"
        f"{marker_end}"
    )


def _decision_summary(decision_file: Path) -> str:
    fields = (
        ("Evidence", "Evidence"),
        ("Uncertainty", "Uncertainty"),
        ("Remaining unknown", "What remains unknown"),
        ("Next smallest step", "Next smallest step"),
    )
    lines = [f"- {label}: {_compact_field(decision_file, field)}" for label, field in fields]
    return "".join(f"{line}\n" for line in lines)


def _close_decision_summary(decision_file: Path, status: str) -> str:
    fields = (
        ("Evidence", "Evidence"),
        ("Uncertainty", "Uncertainty"),
        ("Remaining unknown", "What remains unknown"),
    )
    lines = [f"- {label}: {_compact_field(decision_file, field)}" for label, field in fields]
    lines.append(f"- Next smallest step: none; session is {status}")
    return "".join(f"{line}\n" for line in lines)


def _compact_field(decision_file: Path, field: str) -> str:
    raw_value = documents.field_text(decision_file, field)
    compact = " ".join(raw_value.split())
    if not _meaningful(compact):
        return "none recorded"
    if len(compact) > 240:
        return compact[:237].rstrip() + "..."
    return compact


def _meaningful(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(normalized and normalized not in {"-", "...", "tbd", "todo", "n/a", "not applicable", "none recorded"})


def _append_abandon_records(session_dir: Path, reason: str, round_number: int, now: str) -> None:
    _append_text(
        session_dir / "decision-ledger.md",
        "\n"
        "## Session Abandoned\n\n"
        f"- Reason: {reason}\n"
        f"- Round: {round_number:03d}\n"
        f"- Abandoned at UTC: {now}\n"
        "- Scientific outcome claimed: none\n",
    )
    _append_text(
        session_dir / "progress.md",
        "\n"
        "## Abandon Record\n\n"
        f"- Reason: {reason}\n"
        f"- Round: {round_number:03d}\n"
        "- Scientific outcome claimed: none\n",
    )


def _append_text(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)

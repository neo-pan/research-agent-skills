"""Session state transitions for RDL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import documents, store, templates
from .model import Blocker, CloseOutcome, SessionPhase, SessionStatus
from .protocol import descriptor


@dataclass(frozen=True)
class TransitionResult:
    phase: str
    round: int
    next_action: str


class TransitionBlocked(Exception):
    def __init__(self, blocker: Blocker):
        super().__init__(blocker.message)
        self.blocker = blocker


def advance(session: Any) -> TransitionResult:
    state = session.state
    current_round = state.round
    next_round = current_round + 1
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

    next_round_dir.mkdir(parents=True)
    prompt_path = next_round_dir / "prompt.md"
    templates.write_prompt(
        prompt_path,
        state.mode,
        next_round,
        f"Continue {state.mode} session {state.session_id}",
        previous_decision,
    )

    now = now_utc()
    _update_state(
        session.root,
        {
            "round": next_round,
            "phase": SessionPhase.PLAN.value,
            "updated_at_utc": now,
        },
    )
    _append_round_decision(session.root, current_round, decision, expected_closes, next_loop, next_round)
    return TransitionResult(SessionPhase.PLAN.value, next_round, str(prompt_path))


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
    updates: dict[str, object] = {"updated_at_utc": now_utc()}
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
    decision: str,
    expected_closes: str,
    next_loop: str,
    next_round: int,
) -> None:
    _append_text(
        session_dir / "decision-ledger.md",
        "\n"
        f"## Round {round_number} Decision\n\n"
        f"- Decision: {decision}\n"
        f"- Closes: {expected_closes}\n"
        f"- Recommended next loop: {next_loop}\n"
        f"- Next round: {next_round:03d}\n",
    )


def _append_close_record(session_dir: Path, outcome: str, expected_closes: str, round_number: int, now: str) -> None:
    _append_text(
        session_dir / "decision-ledger.md",
        "\n"
        "## Session Closed\n\n"
        f"- Outcome: {outcome}\n"
        f"- Decision: close-{outcome}\n"
        f"- Closes: {expected_closes}\n"
        f"- Round: {round_number:03d}\n"
        f"- Closed at UTC: {now}\n",
    )


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

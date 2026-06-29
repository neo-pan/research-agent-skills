"""Thin command-line entry point for the Python RDL package."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict

from . import documents, integrity, readiness, templates, transition
from .model import Blocker, CommandResult
from .protocol import descriptor
from .session import SessionStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rdl",
        description="Research Development Loop Python implementation slice.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    for command in ("start", "status", "repair"):
        subparser = subparsers.add_parser(
            command,
            help="reserved; use the Bash RDL CLI for full behavior",
        )
        subparser.add_argument("--json", action="store_true")
        subparser.set_defaults(command=command)

    review = subparsers.add_parser("review", help="prepare or validate the current RDL review")
    review.add_argument("--json", action="store_true")
    review.set_defaults(command="review")

    decide = subparsers.add_parser("decide", help="prepare or validate the current RDL decision")
    decide.add_argument("decision_type", nargs="?")
    decide.add_argument("--json", action="store_true")
    decide.set_defaults(command="decide")

    guard_stop = subparsers.add_parser("guard-stop", help="run RDL guard stop transition")
    guard_stop.add_argument("--guard-session-id")
    guard_stop.add_argument("--guard-command-id")
    guard_stop.add_argument("--json", action="store_true")
    guard_stop.set_defaults(command="guard-stop")

    abandon = subparsers.add_parser("abandon", help="abandon the active RDL session")
    abandon.add_argument("reason", nargs="*")
    abandon.add_argument("--json", action="store_true")
    abandon.set_defaults(command="abandon")

    next_command = subparsers.add_parser("next", help="advance the active RDL session")
    next_command.add_argument("--json", action="store_true")
    next_command.set_defaults(command="next")

    close = subparsers.add_parser("close", help="close the active RDL session")
    close.add_argument("outcome", nargs="?")
    close.add_argument("--json", action="store_true")
    close.set_defaults(command="close")

    doctor = subparsers.add_parser("doctor", help="inspect the active RDL session")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(command="doctor")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        raise
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "doctor":
        result = _doctor()
        _emit(result, json_output=args.json)
        if result.status == "error":
            return 1
        if result.status == "blocked":
            return 2
        return 0

    if args.command == "next":
        result = _next()
        _emit(result, json_output=args.json)
        if result.status == "error":
            return 1
        if result.status == "blocked":
            return 2
        return 0

    if args.command == "close":
        result = _close(args.outcome)
        _emit(result, json_output=args.json)
        if result.status == "error":
            return 1
        if result.status == "blocked":
            return 2
        return 0

    if args.command == "abandon":
        result = _abandon(args.reason)
        _emit(result, json_output=args.json)
        if result.status == "error":
            return 1
        if result.status == "blocked":
            return 2
        return 0

    if args.command == "guard-stop":
        result = _guard_stop(args.guard_session_id, args.guard_command_id)
        _emit(result, json_output=args.json)
        if result.status == "error":
            return 1
        if result.status == "blocked":
            return 2
        return 0

    if args.command == "review":
        result = _review()
        _emit(result, json_output=args.json)
        if result.status == "error":
            return 1
        if result.status == "blocked":
            return 2
        return 0

    if args.command == "decide":
        result = _decide(args.decision_type)
        _emit(result, json_output=args.json)
        if result.status == "error":
            return 1
        if result.status == "blocked":
            return 2
        return 0

    parser.error(
        f"{args.command!r} is not implemented in the Python phase-1 slice; "
        "use the existing Bash RDL CLI for full command behavior."
    )
    return 2


def _doctor() -> CommandResult:
    loaded = _active_session_result("doctor")
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded

    blockers = tuple(readiness.check(session, "doctor-current"))
    state = session.state
    if blockers:
        return CommandResult(
            status="blocked",
            action="doctor",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(blockers),
            blockers=blockers,
            next_action="complete missing RDL records",
        )

    return CommandResult(
        status="ok",
        action="doctor",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=str(state.phase),
        round=state.round,
        next_action="rdl review",
    )


def _next() -> CommandResult:
    loaded = _active_session_result("next")
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded
    state = session.state

    blockers = tuple(readiness.check(session, "advance"))
    if blockers:
        return CommandResult(
            status="blocked",
            action="next",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(blockers),
            blockers=blockers,
            next_action="complete current round review and decision",
        )

    try:
        result = transition.advance(session)
    except transition.TransitionBlocked as exc:
        return CommandResult(
            status="blocked",
            action="next",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers((exc.blocker,)),
            blockers=(exc.blocker,),
            next_action="inspect existing next round",
        )

    try:
        refreshed = SessionStore.cwd().active_session()
        if refreshed is None:
            raise ValueError("active session disappeared after transition")
        integrity.refresh(refreshed)
    except Exception as exc:
        return _integrity_refresh_error("next", state, result.phase, result.round, exc)

    return CommandResult(
        status="ok",
        action="next",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=result.phase,
        round=result.round,
        next_action=result.next_action,
    )


def _review() -> CommandResult:
    loaded = _active_session_result("review")
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded
    state = session.state
    review_file = session.round_dir() / "review.md"

    if not review_file.is_file():
        try:
            templates.copy_template("review.md", review_file)
        except Exception as exc:
            return _template_write_error("review", state, str(state.phase), state.round, exc)
        try:
            integrity.refresh(SessionStore.cwd().load_session(session.root))
        except Exception as exc:
            return _integrity_refresh_error("review", state, str(state.phase), state.round, exc)
        return CommandResult(
            status="ok",
            action="review",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            next_action=str(review_file),
        )

    blockers = tuple(documents.validate("review", review_file))
    if blockers:
        return CommandResult(
            status="blocked",
            action="review",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(blockers),
            blockers=blockers,
            next_action="complete review.md",
        )

    return CommandResult(
        status="ok",
        action="review",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=str(state.phase),
        round=state.round,
        next_action="rdl decide <decision-type>",
    )


def _decide(decision_type: str | None) -> CommandResult:
    if not decision_type:
        blocker = Blocker(
            "missing_decision_type",
            "",
            "decide requires a decision type.",
            "rdl decide continue",
        )
        return CommandResult(
            status="error",
            action="decide",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="rdl decide continue",
        )
    if not descriptor.value_allowed("decision-type", decision_type):
        blocker = Blocker(
            "invalid_decision_type",
            "",
            f"unsupported decision type: {decision_type}",
            "Use a planned RDL decision type.",
        )
        return CommandResult(
            status="error",
            action="decide",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="Use a planned RDL decision type.",
        )

    loaded = _active_session_result("decide")
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded
    state = session.state
    decision_file = session.round_dir() / "decision.md"
    expected_closes = descriptor.expected_closes(state.mode)

    if not decision_file.is_file():
        try:
            templates.write_decision(decision_file, decision_type, expected_closes)
        except Exception as exc:
            return _template_write_error("decide", state, str(state.phase), state.round, exc)
        try:
            integrity.refresh(SessionStore.cwd().load_session(session.root))
        except Exception as exc:
            return _integrity_refresh_error("decide", state, str(state.phase), state.round, exc)
        return CommandResult(
            status="ok",
            action="decide",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            next_action=str(decision_file),
        )

    blockers = list(documents.validate("decision", decision_file, {"expected_closes": expected_closes}))
    if documents.field(decision_file, "Decision") != decision_type:
        blockers.append(
            Blocker(
                "decision_type_mismatch",
                f"{decision_file}#Decision",
                "Decision does not match the requested decision type.",
                "Run rdl decide with the recorded decision type or update decision.md.",
            )
        )
    if blockers:
        return CommandResult(
            status="blocked",
            action="decide",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(blockers),
            blockers=tuple(blockers),
            next_action="complete decision.md",
        )

    return CommandResult(
        status="ok",
        action="decide",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=str(state.phase),
        round=state.round,
        next_action="rdl next",
    )


def _close(outcome: str | None) -> CommandResult:
    if not outcome:
        blocker = Blocker(
            "missing_close_outcome",
            "",
            "close requires positive, negative, or inconclusive.",
            "rdl close positive",
        )
        return CommandResult(
            status="error",
            action="close",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="rdl close positive",
        )
    if not descriptor.value_allowed("close-outcome", outcome):
        blocker = Blocker(
            "invalid_close_outcome",
            "",
            f"unsupported close outcome: {outcome}",
            "Use rdl close positive, negative, or inconclusive.",
        )
        return CommandResult(
            status="error",
            action="close",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="Use rdl close positive, negative, or inconclusive.",
        )

    loaded = _active_session_result("close")
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded
    state = session.state
    blockers = list(readiness.check(session, "advance"))
    blockers.extend(readiness.check(session, "close", outcome=outcome))

    decision_file = session.round_dir() / "decision.md"
    expected_decision = f"close-{outcome}"
    if decision_file.is_file() and documents.field(decision_file, "Decision") != expected_decision:
        blockers.append(
            Blocker(
                "invalid_close_decision",
                f"{decision_file}#Decision",
                f"Close outcome requires Decision: {expected_decision}.",
                f"Run rdl decide {expected_decision} or update decision.md.",
            )
        )

    if blockers:
        return CommandResult(
            status="blocked",
            action="close",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(blockers),
            blockers=tuple(blockers),
            next_action="complete close records",
        )

    result = transition.close(session, outcome)
    try:
        integrity.refresh(SessionStore.cwd().load_session(session.root))
    except Exception as exc:
        return _integrity_refresh_error("close", state, result.phase, result.round, exc)

    return CommandResult(
        status="ok",
        action="close",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=result.phase,
        round=result.round,
        next_action=result.next_action,
    )


def _abandon(reason_parts: Sequence[str]) -> CommandResult:
    reason = " ".join(reason_parts).strip()
    if not reason:
        blocker = Blocker(
            "missing_abandon_reason",
            "",
            "abandon requires a non-empty reason.",
            "rdl abandon <reason>",
        )
        return CommandResult(
            status="error",
            action="abandon",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="rdl abandon <reason>",
        )

    loaded = _active_session_result("abandon")
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded
    state = session.state

    result = transition.abandon(session, reason)
    try:
        integrity.refresh(SessionStore.cwd().load_session(session.root))
    except Exception as exc:
        return _integrity_refresh_error("abandon", state, result.phase, result.round, exc)

    return CommandResult(
        status="ok",
        action="abandon",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=result.phase,
        round=result.round,
        next_action=result.next_action,
    )


def _guard_stop(guard_session_id: str | None, guard_command_id: str | None) -> CommandResult:
    try:
        session = SessionStore.cwd().active_session()
    except ValueError:
        return CommandResult(
            status="error",
            action="guard-stop",
            blockers=(
                Blocker(
                    "multiple_active_sessions",
                    ".rdl/sessions",
                    "Multiple active RDL sessions exist.",
                    "Close or abandon all but one active session.",
                ),
            ),
            next_action="repair RDL session metadata",
        )

    if session is None:
        return CommandResult(status="ok", action="guard-stop", next_action="allow")

    state = session.state
    if guard_session_id and guard_session_id != state.session_id:
        return CommandResult(
            status="ok",
            action="guard-stop",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            next_action="allow",
        )
    if guard_command_id and guard_command_id == state.last_guard_command_id:
        return CommandResult(
            status="ok",
            action="guard-stop",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            next_action="allow",
        )

    audit = session.audit()
    if audit.errors:
        return CommandResult(
            status="error",
            action="guard-stop",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round if state.round > 0 else 0,
            missing=_missing_from_blockers(audit.errors),
            blockers=audit.errors,
            next_action="block",
        )
    if audit.blockers:
        return CommandResult(
            status="blocked",
            action="guard-stop",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(audit.blockers),
            blockers=audit.blockers,
            next_action="block",
        )

    blockers = _guard_stop_readiness(session)
    if blockers:
        return CommandResult(
            status="blocked",
            action="guard-stop",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(blockers),
            blockers=tuple(blockers),
            next_action="block",
        )

    try:
        result = transition.from_decision(session)
    except transition.TransitionBlocked as exc:
        return CommandResult(
            status="blocked",
            action="guard-stop",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers((exc.blocker,)),
            blockers=(exc.blocker,),
            next_action="block",
        )

    if (guard_session_id and guard_session_id != state.guard_session_id) or (guard_command_id and guard_command_id != state.last_guard_command_id):
        transition.mark_guard_seen(SessionStore.cwd().load_session(session.root), guard_session_id, guard_command_id)

    try:
        integrity.refresh(SessionStore.cwd().load_session(session.root))
    except Exception as exc:
        return _integrity_refresh_error("guard-stop", state, result.phase, result.round, exc)

    return CommandResult(
        status="ok",
        action="guard-stop",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=result.phase,
        round=result.round,
        next_action=result.next_action,
    )


def _guard_stop_readiness(session) -> list[Blocker]:
    blockers = list(readiness.check(session, "guard-stop-advance"))
    decision = documents.field(session.round_dir() / "decision.md", "Decision")
    outcome = _close_outcome_for_decision(decision)
    if outcome:
        blockers.extend(readiness.check(session, "guard-stop-close", outcome=outcome))
    return blockers


def _close_outcome_for_decision(decision: str) -> str:
    return {
        "close-positive": "positive",
        "close-negative": "negative",
        "close-inconclusive": "inconclusive",
    }.get(decision, "")


def _active_session_result(action: str):
    try:
        session = SessionStore.cwd().active_session()
    except ValueError:
        return CommandResult(
            status="error",
            action=action,
            blockers=(
                Blocker(
                    "multiple_active_sessions",
                    ".rdl/sessions",
                    "Multiple active RDL sessions exist.",
                    "Close or abandon all but one active session.",
                ),
            ),
            next_action="repair RDL session metadata",
        )

    if session is None:
        return CommandResult(
            status="blocked",
            action=action,
            blockers=(
                Blocker(
                    "no_active_session",
                    ".rdl/sessions",
                    "No active RDL session exists.",
                    "Start an RDL session.",
                ),
            ),
            next_action="rdl start research <mission.md>",
        )

    audit = session.audit()
    state = session.state
    if audit.errors:
        return CommandResult(
            status="error",
            action=action,
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round if state.round > 0 else 0,
            missing=_missing_from_blockers(audit.errors),
            blockers=audit.errors,
            next_action="repair RDL session metadata",
        )
    if audit.blockers:
        return CommandResult(
            status="blocked",
            action=action,
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(audit.blockers),
            blockers=audit.blockers,
            next_action="complete missing RDL records",
        )

    return session


def _integrity_refresh_error(action: str, state, phase: str, round_number: int, exc: Exception) -> CommandResult:
    blocker = Blocker(
        "integrity_refresh_failed",
        "integrity.json",
        f"Integrity refresh failed: {exc}",
        "Inspect the session and run rdl repair when available.",
    )
    return CommandResult(
        status="error",
        action=action,
        session_id=state.session_id,
        mode=str(state.mode),
        phase=phase,
        round=round_number,
        missing=_missing_from_blockers((blocker,)),
        blockers=(blocker,),
        next_action="repair RDL session metadata",
    )


def _template_write_error(action: str, state, phase: str, round_number: int, exc: Exception) -> CommandResult:
    blocker = Blocker(
        "template_write_failed",
        "templates",
        f"Template write failed: {exc}",
        "Inspect RDL templates and retry the command.",
    )
    return CommandResult(
        status="error",
        action=action,
        session_id=state.session_id,
        mode=str(state.mode),
        phase=phase,
        round=round_number,
        missing=_missing_from_blockers((blocker,)),
        blockers=(blocker,),
        next_action="repair RDL templates",
    )


def _emit(result: CommandResult, json_output: bool) -> None:
    if json_output:
        print(json.dumps(_result_dict(result), sort_keys=True))
        return
    if result.status == "ok":
        print(f"ok: {result.action} {result.next_action}")
        return
    for blocker in result.blockers:
        print(f"{result.status}: {blocker.code}: {blocker.message}")


def _missing_from_blockers(blockers: Sequence[Blocker]) -> tuple[str, ...]:
    missing: list[str] = []
    seen: set[str] = set()
    for blocker in blockers:
        path = blocker.file
        if path and path not in seen:
            seen.add(path)
            missing.append(path)
    return tuple(missing)


def _result_dict(result: CommandResult) -> dict[str, object]:
    return {
        "status": result.status,
        "action": result.action,
        "session_id": result.session_id,
        "mode": result.mode,
        "phase": result.phase,
        "round": result.round,
        "missing": list(result.missing),
        "warnings": list(result.warnings),
        "blockers": [asdict(blocker) for blocker in result.blockers],
        "next_action": result.next_action,
    }

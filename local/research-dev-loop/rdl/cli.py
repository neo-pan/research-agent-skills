"""Thin command-line entry point for the Python RDL package."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path

from . import documents, integrity, readiness, repair, templates, transition
from .model import Blocker, CommandResult, SessionMode, SessionPhase, SessionState, SessionStatus
from .protocol import descriptor
from .session import Session, SessionStore, SessionLockError, acquire_session_lock, valid_session_id


class RdlArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise RdlParserError(message)


class RdlParserError(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = RdlArgumentParser(
        prog="rdl",
        description="Research Development Loop CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    repair_command = subparsers.add_parser("repair", help="repair safe RDL session metadata")
    repair_command.add_argument("--json", action="store_true")
    repair_command.set_defaults(command="repair")

    start = subparsers.add_parser("start", help="start a new RDL session")
    start.add_argument("mode", nargs="?")
    start.add_argument("mission_file", nargs="?")
    start.add_argument("--session-id")
    start.add_argument("--json", action="store_true")
    start.set_defaults(command="start")

    status = subparsers.add_parser("status", help="inspect the active RDL session lifecycle status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(command="status")

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
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except RdlParserError as exc:
        if "--json" in argv:
            result = _parser_error_result(argv, str(exc))
            _emit(result, json_output=True)
            return 1
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {exc}", file=sys.stderr)
        return 2
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

    if args.command == "start":
        result = _start(args.mode, args.mission_file, args.session_id)
        _emit(result, json_output=args.json)
        if result.status == "error":
            return 1
        if result.status == "blocked":
            return 2
        return 0

    if args.command == "status":
        result = _status()
        _emit(result, json_output=args.json)
        if result.status == "error":
            return 1
        if result.status == "blocked":
            return 2
        return 0

    if args.command == "repair":
        result = _repair()
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

    parser.error(f"unsupported command: {args.command!r}")
    return 2


def _parser_error_result(argv: Sequence[str], message: str) -> CommandResult:
    action = argv[0] if argv else ""
    code = "parser_error"
    next_action = "Run rdl --help."
    detail = message
    if "invalid choice" in message:
        code = "unknown_command"
        detail = f"unknown command: {action}"
    elif "expected one argument" in message:
        option = _missing_value_option(argv)
        detail = f"{option} requires a value." if option else message
        code, next_action = _missing_value_code(action, option)
    elif "unrecognized arguments:" in message:
        option = message.split("unrecognized arguments:", 1)[1].strip().split()[0]
        detail = f"unknown option: {option}"
        code = "unknown_option"
    blocker = Blocker(code, "", detail, next_action)
    return CommandResult(
        status="error",
        action=action,
        missing=_missing_from_blockers((blocker,)),
        blockers=(blocker,),
        next_action=next_action,
    )


def _missing_value_option(argv: Sequence[str]) -> str:
    for index, token in enumerate(argv):
        if token in {"--session-id", "--guard-session-id", "--guard-command-id"}:
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                return token
    return ""


def _missing_value_code(action: str, option: str) -> tuple[str, str]:
    if action == "start" and option == "--session-id":
        return "missing_session_id", "Pass --session-id <id>."
    if action == "guard-stop" and option == "--guard-session-id":
        return "missing_guard_session_id", "Pass --guard-session-id <id>."
    if action == "guard-stop" and option == "--guard-command-id":
        return "missing_guard_command_id", "Pass --guard-command-id <id>."
    return "missing_option_value", "Run rdl --help."


def _start(mode: str | None, mission_file: str | None, session_id: str | None) -> CommandResult:
    if not mode or not mission_file:
        blocker = Blocker(
            "missing_arguments",
            "",
            "start requires mode and mission file.",
            "rdl start research <mission.md>",
        )
        return CommandResult(
            status="error",
            action="start",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="rdl start research <mission.md>",
        )
    if mode not in {SessionMode.RESEARCH.value, SessionMode.BUILD.value}:
        blocker = Blocker(
            "invalid_mode",
            "",
            "mode must be research or build.",
            "Use rdl start research or rdl start build.",
        )
        return CommandResult(
            status="error",
            action="start",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="Use rdl start research or rdl start build.",
        )

    mission_path = Path(mission_file)
    if not mission_path.is_file():
        blocker = Blocker(
            "missing_mission_file",
            mission_file,
            f"mission file not found: {mission_file}",
            "Create the mission file or pass an existing file.",
        )
        return CommandResult(
            status="error",
            action="start",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="Create the mission file or pass an existing file.",
        )

    store = SessionStore.cwd()
    new_session_id = session_id or transition.now_utc().replace("T", "-").replace(":", "").removesuffix("Z")
    if not valid_session_id(new_session_id):
        blocker = Blocker(
            "invalid_session_id",
            "",
            "session id may contain only letters, numbers, dot, underscore, and dash.",
            "Choose a simpler --session-id.",
        )
        return CommandResult(
            status="error",
            action="start",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="Choose a simpler --session-id.",
        )
    session_dir = store.sessions_root / new_session_id
    if session_dir.exists():
        blocker = Blocker(
            "session_already_exists",
            str(session_dir),
            "A session with this id already exists.",
            "Choose a different --session-id.",
        )
        return CommandResult(
            status="blocked",
            action="start",
            session_id=new_session_id,
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="choose a different --session-id",
        )

    try:
        existing = store.active_session()
    except ValueError:
        return CommandResult(
            status="error",
            action="start",
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
    if existing is not None:
        audit = existing.audit()
        if audit.errors:
            state = existing.state
            return CommandResult(
                status="error",
                action="start",
                session_id=state.session_id,
                mode=str(state.mode),
                phase=str(state.phase),
                round=state.round if state.round > 0 else 0,
                missing=_missing_from_blockers(audit.errors),
                blockers=audit.errors,
                next_action="repair RDL session metadata",
            )
        state = existing.state
        blocker = Blocker(
            "active_session_exists",
            str(existing.root / "state.json"),
            "An active RDL session already exists.",
            "Run rdl status, then close or abandon the active session before starting another.",
        )
        return CommandResult(
            status="blocked",
            action="start",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="rdl status",
        )

    try:
        session = store.create_session(mode, mission_path, new_session_id)
    except FileNotFoundError as exc:
        return _template_write_error("start", _synthetic_state(new_session_id, mode), "plan", 1, exc)
    except Exception as exc:
        state = _synthetic_state(new_session_id, mode)
        return _integrity_refresh_error("start", state, "plan", 1, exc)

    state = session.state
    return CommandResult(
        status="ok",
        action="start",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=str(state.phase),
        round=state.round,
        next_action=str(session.round_dir(1) / "prompt.md"),
    )


def _status() -> CommandResult:
    try:
        session = SessionStore.cwd().active_session()
    except ValueError:
        return CommandResult(
            status="error",
            action="status",
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
        return CommandResult(status="ok", action="status", next_action="rdl start research <mission.md>")

    state = session.state
    state_errors = session.state_errors()
    if state_errors:
        return CommandResult(
            status="error",
            action="status",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round if state.round > 0 else 0,
            missing=_missing_from_blockers(state_errors),
            blockers=state_errors,
            next_action="repair RDL session metadata",
        )
    return CommandResult(
        status="ok",
        action="status",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=str(state.phase),
        round=state.round,
        next_action=str(state.status),
    )


def _synthetic_state(session_id: str, mode: str) -> SessionState:
    return SessionState(
        schema_version=1,
        session_id=session_id,
        mode=SessionMode(mode),
        phase=SessionPhase.PLAN,
        round=1,
        status=SessionStatus.ACTIVE,
        mission_file="mission.md",
    )


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


def _repair() -> CommandResult:
    loaded = _active_session_result("repair", audit=False)
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded
    state = session.state

    result = repair.repair(session)
    if result.errors:
        return CommandResult(
            status="error",
            action="repair",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(result.errors),
            blockers=result.errors,
            next_action="restore unsafe files before repair",
        )
    if result.blockers:
        next_action = (
            "retry after lock clears"
            if any(blocker.code in {"session_locked", "stale_lock"} for blocker in result.blockers)
            else "restore unsafe files before repair"
        )
        return CommandResult(
            status="blocked",
            action="repair",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(result.blockers),
            blockers=result.blockers,
            next_action=next_action,
        )

    repaired_session = SessionStore.cwd().load_session(session.root)
    audit = repaired_session.audit()
    if audit.errors:
        return CommandResult(
            status="error",
            action="repair",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(audit.errors),
            blockers=audit.errors,
            next_action="inspect repaired session",
        )
    if audit.blockers:
        return CommandResult(
            status="blocked",
            action="repair",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(audit.blockers),
            blockers=audit.blockers,
            next_action="inspect repaired session",
        )

    return CommandResult(
        status="ok",
        action="repair",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=str(state.phase),
        round=state.round,
        next_action=",".join(result.repaired),
    )


def _next() -> CommandResult:
    return _run_locked_session("next", _next_locked)


def _next_locked(session: Session) -> CommandResult:
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
    return _run_locked_session("review", _review_locked)


def _review_locked(session: Session) -> CommandResult:
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

    return _run_locked_session("decide", lambda session: _decide_locked(session, decision_type))


def _decide_locked(session: Session, decision_type: str) -> CommandResult:
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

    return _run_locked_session("close", lambda session: _close_locked(session, outcome))


def _close_locked(session: Session, outcome: str) -> CommandResult:
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

    return _run_locked_session("abandon", lambda session: _abandon_locked(session, reason))


def _abandon_locked(session: Session, reason: str) -> CommandResult:
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

    return _run_locked_session(
        "guard-stop",
        lambda locked_session: _guard_stop_locked(locked_session, guard_session_id, guard_command_id),
        session=session,
        audit=False,
    )


def _guard_stop_locked(session: Session, guard_session_id: str | None, guard_command_id: str | None) -> CommandResult:
    state = session.state

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
    outcome = descriptor.close_outcome_for_decision(decision)
    if outcome:
        blockers.extend(readiness.check(session, "guard-stop-close", outcome=outcome))
    return blockers


def _run_locked_session(
    action: str,
    body: Callable[[Session], CommandResult],
    *,
    session: Session | None = None,
    audit: bool = True,
) -> CommandResult:
    loaded = session if session is not None else _active_session_result(action, audit=False)
    if isinstance(loaded, CommandResult):
        return loaded
    state = loaded.state
    try:
        with acquire_session_lock(loaded, action):
            locked_session = SessionStore.cwd().load_session(loaded.root)
            if audit:
                audit_result = locked_session.audit()
                state = locked_session.state
                if audit_result.errors:
                    return CommandResult(
                        status="error",
                        action=action,
                        session_id=state.session_id,
                        mode=str(state.mode),
                        phase=str(state.phase),
                        round=state.round if state.round > 0 else 0,
                        missing=_missing_from_blockers(audit_result.errors),
                        blockers=audit_result.errors,
                        next_action="repair RDL session metadata",
                    )
                if audit_result.blockers:
                    return CommandResult(
                        status="blocked",
                        action=action,
                        session_id=state.session_id,
                        mode=str(state.mode),
                        phase=str(state.phase),
                        round=state.round,
                        missing=_missing_from_blockers(audit_result.blockers),
                        blockers=audit_result.blockers,
                        next_action="complete missing RDL records",
                    )
            return body(locked_session)
    except SessionLockError as exc:
        return CommandResult(
            status="blocked",
            action=action,
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round if state.round > 0 else 0,
            missing=_missing_from_blockers((exc.blocker,)),
            blockers=(exc.blocker,),
            next_action="retry after lock clears",
        )


def _active_session_result(action: str, audit: bool = True):
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

    if not audit:
        return session

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
        print(json.dumps(_result_dict(result), sort_keys=True, separators=(",", ":")))
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

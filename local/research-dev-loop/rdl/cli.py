"""Thin command-line entry point for the Python RDL package."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict

from . import readiness
from .model import Blocker, CommandResult
from .session import SessionStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rdl",
        description="Research Development Loop Python implementation slice.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    for command in ("start", "status", "review", "decide", "next", "close", "abandon", "guard-stop", "repair"):
        subparser = subparsers.add_parser(
            command,
            help="reserved; use the Bash RDL CLI for full behavior",
        )
        subparser.add_argument("--json", action="store_true")
        subparser.set_defaults(command=command)

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

    parser.error(
        f"{args.command!r} is not implemented in the Python phase-1 slice; "
        "use the existing Bash RDL CLI for full command behavior."
    )
    return 2


def _doctor() -> CommandResult:
    try:
        session = SessionStore.cwd().active_session()
    except ValueError:
        return CommandResult(
            status="error",
            action="doctor",
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
            action="doctor",
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
            action="doctor",
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
            action="doctor",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(audit.blockers),
            blockers=audit.blockers,
            next_action="complete missing RDL records",
        )

    blockers = tuple(readiness.check(session, "doctor-current"))
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

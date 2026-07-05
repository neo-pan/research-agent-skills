"""Thin command-line entry point for the Python RDL package."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict

from .commands import CommandIntent, execute
from .model import Blocker, CommandResult


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
    start.add_argument("--profile")
    start.add_argument("--json", action="store_true")
    start.set_defaults(command="start")

    status = subparsers.add_parser("status", help="inspect the active RDL session lifecycle status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(command="status")

    review = subparsers.add_parser("review", help="prepare or validate the current RDL review")
    review.add_argument("--pack", dest="review_pack", action="store_true")
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
    next_command.add_argument("--mode", dest="next_mode")
    next_command.add_argument("--profile")
    next_command.add_argument("--json", action="store_true")
    next_command.set_defaults(command="next")

    close = subparsers.add_parser("close", help="close the active RDL session")
    close.add_argument("outcome", nargs="?")
    close.add_argument("--json", action="store_true")
    close.set_defaults(command="close")

    doctor = subparsers.add_parser("doctor", help="inspect the active RDL session")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(command="doctor")

    handoff = subparsers.add_parser("handoff", help="print a compact RDL session handoff report")
    handoff.add_argument("--json", action="store_true")
    handoff.set_defaults(command="handoff")

    summarize = subparsers.add_parser("summarize", help="summarize RDL round state into top-level memory")
    summarize_mode = summarize.add_mutually_exclusive_group()
    summarize_mode.add_argument("--check", dest="summarize_mode", action="store_const", const="check")
    summarize_mode.add_argument("--write", dest="summarize_mode", action="store_const", const="write")
    summarize.add_argument("--round", dest="summarize_round", type=int)
    summarize.add_argument("--json", action="store_true")
    summarize.set_defaults(command="summarize", summarize_mode="check")

    memory = subparsers.add_parser("memory", help="inspect and refresh top-level RDL session memory")
    memory_mode = memory.add_mutually_exclusive_group()
    memory_mode.add_argument("--check", dest="memory_mode", action="store_const", const="check")
    memory_mode.add_argument("--write", dest="memory_mode", action="store_const", const="write")
    memory.add_argument("--json", action="store_true")
    memory.set_defaults(command="memory", memory_mode="check")

    progress = subparsers.add_parser("progress", help="record explicit progress session memory")
    progress.add_argument("progress_action", nargs="?")
    progress.add_argument("--item")
    progress.add_argument("--mode")
    progress.add_argument("--text")
    progress.add_argument("--blocking")
    progress.add_argument("--trigger")
    progress.add_argument("--reason")
    progress.add_argument("--needed")
    progress.add_argument("--impact")
    progress.add_argument("--section")
    progress.add_argument("--json", action="store_true")
    progress.set_defaults(command="progress")

    factors = subparsers.add_parser("factors", help="record explicit factor session memory")
    factors.add_argument("factor_action", nargs="?")
    factors.add_argument("--section")
    factors.add_argument("--value")
    factors.add_argument("--json", action="store_true")
    factors.set_defaults(command="factors")

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

    json_output = bool(getattr(args, "json", False))
    intent = _command_intent(args)
    result = execute(intent)
    _emit(result, json_output=json_output)
    return _exit_code(result)


def _command_intent(args: argparse.Namespace) -> CommandIntent:
    return CommandIntent(
        command=args.command,
        mode=getattr(args, "mode", None),
        profile=getattr(args, "profile", None),
        mission_file=getattr(args, "mission_file", None),
        session_id=getattr(args, "session_id", None),
        decision_type=getattr(args, "decision_type", None),
        guard_session_id=getattr(args, "guard_session_id", None),
        guard_command_id=getattr(args, "guard_command_id", None),
        reason_parts=tuple(getattr(args, "reason", ()) or ()),
        outcome=getattr(args, "outcome", None),
        next_mode=getattr(args, "next_mode", None),
        summarize_mode=getattr(args, "summarize_mode", None),
        summarize_round=getattr(args, "summarize_round", None),
        memory_mode=getattr(args, "memory_mode", None),
        progress_action=getattr(args, "progress_action", None),
        factor_action=getattr(args, "factor_action", None),
        item=getattr(args, "item", None),
        text=getattr(args, "text", None),
        blocking=getattr(args, "blocking", None),
        trigger=getattr(args, "trigger", None),
        reason=getattr(args, "reason", None),
        needed=getattr(args, "needed", None),
        impact=getattr(args, "impact", None),
        section=getattr(args, "section", None),
        value=getattr(args, "value", None),
        review_pack=getattr(args, "review_pack", False),
    )


def _exit_code(result: CommandResult) -> int:
    if result.status == "error":
        return 1
    if result.status == "blocked":
        return 2
    return 0


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
        if token in {
            "--session-id",
            "--guard-session-id",
            "--guard-command-id",
            "--mode",
            "--profile",
            "--round",
            "--item",
            "--text",
            "--blocking",
            "--trigger",
            "--reason",
            "--needed",
            "--impact",
            "--section",
            "--value",
        }:
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
    if action == "next" and option == "--mode":
        return "missing_mode", "Pass --mode research or --mode build."
    if option == "--profile":
        return "missing_profile", "Pass --profile full-review, checkpoint, or build-update."
    if action == "summarize" and option == "--round":
        return "missing_round", "Pass --round <number>."
    if action in {"progress", "factors"} and option in {
        "--item",
        "--text",
        "--blocking",
        "--trigger",
        "--reason",
        "--needed",
        "--impact",
        "--section",
        "--value",
    }:
        return "missing_memory_value", f"Pass {option} <value>."
    return "missing_option_value", "Run rdl --help."


def _emit(result: CommandResult, json_output: bool) -> None:
    if json_output:
        print(json.dumps(_result_dict(result), sort_keys=True, separators=(",", ":")))
        return
    if result.status == "ok" and result.action == "handoff":
        _emit_handoff(result)
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


def _emit_handoff(result: CommandResult) -> None:
    details = result.details
    last_decision = details.get("last_decision", {})
    latest_completed_decision = details.get("latest_completed_decision", {})
    memory_details = details.get("memory", {})
    print(f"Session: {result.session_id}")
    print(f"Mode/Profile/Round: {result.mode} / {result.profile} / {result.round}")
    print(f"Handoff Status: {details.get('handoff_status', '')}")
    print()
    _print_section("Current Focus", details.get("current_focus", ""))
    _print_decision_section("Last Decision", last_decision if isinstance(last_decision, dict) else {})
    _print_decision_section(
        "Latest Completed Decision",
        latest_completed_decision if isinstance(latest_completed_decision, dict) else {},
    )
    _print_section("Open Questions", details.get("open_questions", ""))
    _print_section("Known Evidence Gaps", details.get("known_evidence_gaps", ""))
    _print_section("Directions Tried", details.get("directions_tried", ""))
    _print_section("Staleness Watch", details.get("staleness_watch", ""))
    _print_section("Next Smallest Step", details.get("next_smallest_step", ""))
    if isinstance(memory_details, dict):
        print("Memory:")
        print(f"  status: {memory_details.get('memory_status', '')}")
        print(f"  progress gaps: {_join_values(memory_details.get('progress_gaps', []))}")
        print(f"  factor gaps: {_join_values(memory_details.get('factor_gaps', []))}")
        print()
    _print_section("Suggested Actions", _bullet_values(details.get("suggested_actions", [])))


def _print_decision_section(title: str, decision_details: dict[object, object]) -> None:
    print(f"{title}:")
    if "round" in decision_details:
        print(f"  round: {decision_details.get('round', '')}")
    print(f"  decision: {decision_details.get('decision', '')}")
    print(f"  closes: {decision_details.get('closes', '')}")
    print(f"  evidence: {decision_details.get('evidence', '')}")
    print(f"  uncertainty: {decision_details.get('uncertainty', '')}")
    print(f"  remains unknown: {decision_details.get('what_remains_unknown', '')}")
    print(f"  recommended next loop: {decision_details.get('recommended_next_loop', '')}")
    print()


def _print_section(title: str, value: object) -> None:
    print(f"{title}:")
    text = str(value).strip()
    if not text:
        print("  none recorded")
    else:
        for line in text.splitlines():
            print(f"  {line}")
    print()


def _join_values(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "none"
    return str(value) if value else "none"


def _bullet_values(value: object) -> str:
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value) if value else "none recorded"
    return str(value) if value else "none recorded"


def _result_dict(result: CommandResult) -> dict[str, object]:
    return {
        "status": result.status,
        "action": result.action,
        "session_id": result.session_id,
        "mode": result.mode,
        "profile": result.profile,
        "phase": result.phase,
        "round": result.round,
        "missing": list(result.missing),
        "warnings": list(result.warnings),
        "blockers": [asdict(blocker) for blocker in result.blockers],
        "next_action": result.next_action,
        "details": result.details,
    }

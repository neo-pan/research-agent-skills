"""Seven-command JSON CLI for RDL."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .engine import RdlEngine
from .model import RdlError


class ParserError(Exception):
    pass


class JsonParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ParserError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonParser(prog="rdl", description="Evidence-backed research state.")
    commands = parser.add_subparsers(dest="command", metavar="command")

    start = commands.add_parser("start", help="create a session")
    _input(start)
    start.add_argument("--session-id")

    handoff = commands.add_parser("handoff", help="return compact recovery state")
    _selector(handoff)

    apply = commands.add_parser("apply", help="apply one transactional state delta")
    _input(apply)
    _selector(apply)

    review = commands.add_parser("review", help="project a material review subject")
    review.add_argument("--for", dest="review_for", required=True, choices=("next", "close"))
    _selector(review)

    next_command = commands.add_parser("next", help="advance a ready round")
    next_command.add_argument("--expected-state-version", required=True, type=int)
    _selector(next_command)

    close = commands.add_parser("close", help="close or abandon a session")
    close.add_argument("--expected-state-version", required=True, type=int)
    close.add_argument("--outcome", required=True, choices=("positive", "negative", "inconclusive", "abandoned"))
    close.add_argument("--reason")
    _selector(close)

    doctor = commands.add_parser("doctor", help="diagnose state and local integrity")
    doctor.add_argument("--diagnostics", action="store_true")
    _selector(doctor)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(arguments)
        if args.command is None:
            raise ParserError("a command is required")
        request = _read_input(args.input) if hasattr(args, "input") else None
        result = RdlEngine(Path.cwd()).execute(
            args.command,
            session_id=getattr(args, "session_id", None),
            request=request,
            action=getattr(args, "review_for", None),
            expected_state_version=getattr(args, "expected_state_version", None),
            outcome=getattr(args, "outcome", None),
            reason=getattr(args, "reason", None),
            diagnostics=bool(getattr(args, "diagnostics", False)),
        )
    except ParserError as exc:
        result = RdlError("parser_error", str(exc)).result()
    except RdlError as exc:
        result = exc.result()
    except (OSError, json.JSONDecodeError) as exc:
        result = RdlError("input_error", str(exc)).result()
    except Exception as exc:  # keep the CLI machine-readable at the outermost seam
        result = RdlError("internal_error", str(exc)).result()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    if result.get("status") == "ok":
        return 0
    if result.get("status") == "blocked":
        return 2
    return 1


def _selector(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--session-id")


def _input(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", required=True)


def _read_input(source: str) -> dict[str, Any]:
    if source == "-":
        value = json.load(sys.stdin)
    else:
        with Path(source).open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    if not isinstance(value, dict):
        raise RdlError("invalid_input", "input JSON must be an object")
    return value

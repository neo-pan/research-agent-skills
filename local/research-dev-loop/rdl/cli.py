"""Thin command-line entry point for the Python RDL package."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rdl",
        description="Research Development Loop Python implementation slice.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    for command in (
        "start",
        "status",
        "doctor",
        "review",
        "decide",
        "next",
        "close",
        "abandon",
        "guard-stop",
        "repair",
    ):
        subparser = subparsers.add_parser(
            command,
            help="reserved; use the Bash RDL CLI for full behavior",
        )
        subparser.set_defaults(command=command)

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

    parser.error(
        f"{args.command!r} is not implemented in the Python phase-1 slice; "
        "use the existing Bash RDL CLI for full command behavior."
    )
    return 2

#!/usr/bin/env python3
"""Report whether this repository matches a prospective Codex launch environment."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from install_rdl_command import (
    InstallerError,
    bin_directory,
    canonical_source,
    collect_status,
    path_state,
)
from lib.installation_state import InstallationStateError, build_report, render_text
from lib.repository_links import RepositoryLinksError


class _StatusParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    parser = _StatusParser(
        description="Report repository-managed Codex installation state."
    )
    parser.add_argument("--codex-home")
    parser.add_argument("--skills-dir")
    parser.add_argument("--agents-dir")
    parser.add_argument("--rdl-bin-dir")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = build_report(
        Path(__file__).resolve().parents[1],
        codex_home=args.codex_home,
        skills_dir=args.skills_dir,
        agents_dir=args.agents_dir,
        environment=os.environ,
    )
    if args.rdl_bin_dir is not None:
        command_report = collect_status(
            bin_directory(args.rdl_bin_dir),
            canonical_source(),
            path_state(os.environ.get("PATH", "")),
        )
        report["rdl_command"] = command_report
        if not _rdl_healthy(command_report):
            report["status"] = "mismatch"
            report["findings"].append(
                {
                    "code": "rdl_command_mismatch",
                    "severity": "blocking",
                    "target": str(command_report["target"]),
                    "remediation": "resolve the reported PATH or link state, then rerun "
                    "the explicit RDL installer",
                }
            )
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    else:
        print(render_text(report))
    return 0 if report["status"] == "ok" else 2


def _rdl_healthy(report: dict[str, object]) -> bool:
    return bool(
        report["state"] == "current"
        and report["on_path"]
        and not report["path_unsafe"]
        and report["shadowed_by"] is None
        and report["source_available"]
    )


def main() -> int:
    try:
        return run()
    except (
        InstallationStateError,
        InstallerError,
        RepositoryLinksError,
        OSError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

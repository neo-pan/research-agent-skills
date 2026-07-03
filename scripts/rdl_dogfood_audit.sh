#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/rdl_dogfood_audit.sh <project-root>

Run a read-only RDL dogfood takeover audit against an external project root.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "$#" -ne 1 ]]; then
  usage >&2
  exit 1
fi

PROJECT_ROOT_INPUT="$1"
if [[ ! -d "${PROJECT_ROOT_INPUT}" ]]; then
  echo "error: project root is not a directory" >&2
  exit 1
fi
PROJECT_ROOT="$(cd "${PROJECT_ROOT_INPUT}" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 is required" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

run_rdl_json() {
  local name="$1"
  shift

  set +e
  (
    cd "${PROJECT_ROOT}"
    PYTHONPATH="${ROOT_DIR}/local/research-dev-loop" python3 -m rdl "$@" --json
  ) >"${tmp_dir}/${name}.json" 2>"${tmp_dir}/${name}.stderr"
  local status=$?
  set -e

  printf '%s\n' "${status}" >"${tmp_dir}/${name}.status"
}

run_rdl_json handoff handoff
run_rdl_json memory memory --check
run_rdl_json summarize summarize --check
run_rdl_json doctor doctor

python3 - "${tmp_dir}" "${PROJECT_ROOT}" "${ROOT_DIR}" <<'PY'
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


COMMANDS = (
    ("handoff", "handoff"),
    ("memory", "memory --check"),
    ("summarize", "summarize --check"),
    ("doctor", "doctor"),
)


def main() -> int:
    tmp_dir = Path(sys.argv[1])
    scrub_paths = tuple(path for path in sys.argv[2:4] if path)
    failed = False
    results: dict[str, dict[str, Any]] = {}

    print("RDL Dogfood Audit")
    print("=================")

    for name, label in COMMANDS:
        code = int((tmp_dir / f"{name}.status").read_text(encoding="utf-8").strip())
        output = (tmp_dir / f"{name}.json").read_text(encoding="utf-8").strip()
        try:
            result = json.loads(output)
        except json.JSONDecodeError:
            failed = True
            print()
            print(f"{label}: invalid-json")
            print(f"  exit: {code}")
            stderr_summary = _stderr_summary(tmp_dir / f"{name}.stderr", scrub_paths)
            if stderr_summary:
                print("  stderr:")
                for line in stderr_summary:
                    print(f"    {line}")
            continue

        results[name] = result
        failed = _print_command(label, code, result) or failed

    failed = _strict_health_failed(results) or failed
    print()
    print(f"Audit: {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


def _print_command(label: str, code: int, result: dict[str, Any]) -> bool:
    details = _dict(result.get("details"))
    blockers = [_dict(blocker).get("code", "") for blocker in _list(result.get("blockers"))]
    blockers = [code for code in blockers if code]

    print()
    print(f"{label}: {result.get('status', 'unknown')}")
    print(f"  exit: {code}")
    if result.get("session_id"):
        print(f"  session: {result.get('session_id')}")
    if result.get("mode") or result.get("profile") or result.get("round"):
        print(f"  mode/profile/round: {result.get('mode', '')} / {result.get('profile', '')} / {result.get('round', '')}")

    if label == "handoff":
        print(f"  handoff_status: {details.get('handoff_status', 'unknown')}")
    elif label == "memory --check":
        print(f"  memory_status: {details.get('memory_status', 'unknown')}")
        print(f"  progress_gaps: {_join(details.get('progress_gaps'))}")
        print(f"  factor_gaps: {_join(details.get('factor_gaps'))}")
    elif label == "summarize --check":
        print(f"  summary_status: {details.get('summary_status', 'unknown')}")

    warnings = _list(result.get("warnings"))
    if warnings:
        print(f"  warnings: {_join(warnings)}")
    if blockers:
        print(f"  blockers: {_join(blockers)}")
    if result.get("next_action"):
        print(f"  next_action: {result.get('next_action')}")

    return code != 0


def _strict_health_failed(results: dict[str, dict[str, Any]]) -> bool:
    if set(results) != {name for name, _label in COMMANDS}:
        return True

    handoff = _dict(results["handoff"].get("details"))
    memory = _dict(results["memory"].get("details"))
    summarize = _dict(results["summarize"].get("details"))
    doctor = results["doctor"]

    return any(
        (
            handoff.get("handoff_status") != "ready",
            memory.get("memory_status") != "healthy",
            summarize.get("summary_status") != "up_to_date",
            doctor.get("status") != "ok",
        )
    )


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _join(value: Any) -> str:
    items = _list(value)
    return ", ".join(str(item) for item in items) if items else "none"


def _stderr_summary(path: Path, scrub_paths: tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = _sanitize_line(line.strip(), scrub_paths)
        if text:
            lines.append(text)
        if len(lines) == 3:
            break
    return lines


def _sanitize_line(line: str, scrub_paths: tuple[str, ...]) -> str:
    text = line
    for index, raw_path in enumerate(scrub_paths):
        placeholder = "<project-root>" if index == 0 else "<skill-pack-root>"
        text = text.replace(raw_path, placeholder)
    return re.sub(r"(?<![\w.-])/(?:tmp|var/tmp)/[^\s'\"),;:]+", "<tmp-path>", text)


if __name__ == "__main__":
    raise SystemExit(main())
PY

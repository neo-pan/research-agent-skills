#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  echo "Usage: scripts/rdl_dogfood_audit.sh [--session-id <id>] [--subagent-calls <count>] [--json-output <path>] <project-root>"
}

SESSION_ID=""
SUBAGENT_CALLS=""
JSON_OUTPUT=""
while [[ "${1:-}" == --* ]]; do
  case "$1" in
    --session-id)
      [[ -n "${2:-}" ]] || { echo "error: --session-id requires a value" >&2; exit 1; }
      SESSION_ID="$2"
      shift 2
      ;;
    --json-output)
      [[ -n "${2:-}" ]] || { echo "error: --json-output requires a path" >&2; exit 1; }
      JSON_OUTPUT="$2"
      shift 2
      ;;
    --subagent-calls)
      [[ -n "${2:-}" ]] || { echo "error: --subagent-calls requires a value" >&2; exit 1; }
      SUBAGENT_CALLS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done
[[ -n "${SUBAGENT_CALLS}" ]] || { echo "error: --subagent-calls is required" >&2; exit 1; }
[[ "${SUBAGENT_CALLS}" =~ ^[0-9]+$ ]] || { echo "error: --subagent-calls must be a non-negative integer" >&2; exit 1; }
[[ "$#" -eq 1 ]] || { usage >&2; exit 1; }
[[ -d "$1" ]] || { echo "error: project root is not a directory" >&2; exit 1; }
PROJECT_ROOT="$(cd "$1" && pwd)"

python3 - \
  "${ROOT_DIR}/local/research-dev-loop/bin/rdl" \
  "${PROJECT_ROOT}" \
  "${SESSION_ID}" \
  "${JSON_OUTPUT}" \
  "${SUBAGENT_CALLS}" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


launcher = Path(sys.argv[1]).resolve()
project_root = Path(sys.argv[2]).resolve()
requested_session = sys.argv[3]
json_output = Path(sys.argv[4]).resolve() if sys.argv[4] else None
reported_subagent_calls = int(sys.argv[5])
selector = ["--session-id", requested_session] if requested_session else []


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def run_probe(name: str, arguments: list[str], input_value: dict[str, Any] | None = None) -> dict[str, Any]:
    argv = [str(launcher), *arguments, *selector]
    completed = subprocess.run(
        argv,
        cwd=project_root,
        input=(canonical(input_value) + "\n") if input_value is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )
    raw = completed.stdout.strip()
    diagnostic = completed.stderr.strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "status": "error",
            "code": "bootstrap_error" if diagnostic else "invalid_json",
        }
    decisive = {
        key: result[key]
        for key in ("status", "code", "session_id", "session_status", "state_version", "findings")
        if key in result
    }
    return {
        "name": name,
        "argv": argv,
        "input": input_value,
        "exit_code": completed.returncode,
        "typed_result": decisive,
        "stdout_json": result,
        "stdout_raw": completed.stdout,
        "stderr": diagnostic,
    }


def tree_digest(root: Path) -> dict[str, Any]:
    hasher = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if path.is_symlink():
            kind = b"L"
            payload = os.readlink(path).encode("utf-8")
        elif path.is_dir():
            kind = b"D"
            payload = b""
        else:
            kind = b"F"
            payload = path.read_bytes()
        hasher.update(kind + b"\0" + relative + b"\0" + payload + b"\0")
    return {
        "algorithm": "sha256-tree-v1:path-type-content",
        "digest_root": str(root),
        "exclusions": [],
        "sha256": hasher.hexdigest(),
    }


def snapshot(session_id: str) -> dict[str, Any]:
    pointer = project_root / ".rdl" / "sessions" / session_id
    generation = pointer.resolve(strict=True)
    store = project_root / ".rdl" / ".store" / session_id
    state = json.loads((generation / "state.json").read_text(encoding="utf-8"))
    return {
        "pointer_target": os.readlink(pointer),
        "pointer_resolved": str(generation),
        "generation_set": sorted(path.name for path in store.iterdir()),
        "state_version": state["state_version"],
        "store_digest": tree_digest(store),
    }


def expected(probe: dict[str, Any], *, exit_code: int, status: str, code: str | None = None) -> bool:
    typed = probe["typed_result"]
    return (
        probe["exit_code"] == exit_code
        and typed.get("status") == status
        and (code is None or typed.get("code") == code)
    )


def discover_active_session() -> str | None:
    sessions_root = project_root / ".rdl" / "sessions"
    if not sessions_root.is_dir():
        return None
    active = []
    for pointer in sorted(sessions_root.iterdir()):
        if not pointer.is_symlink():
            continue
        try:
            state = json.loads((pointer.resolve(strict=True) / "state.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if state.get("status") == "active":
            active.append(pointer.name)
    return active[0] if len(active) == 1 else None


probes: list[dict[str, Any]] = []
selected_session = requested_session or discover_active_session()
if selected_session and not requested_session:
    selector[:] = ["--session-id", selected_session]
initial_before = None
if selected_session:
    try:
        initial_before = snapshot(selected_session)
    except (OSError, json.JSONDecodeError, KeyError):
        pass
handoff = run_probe("handoff", ["handoff"])
probes.append(handoff)
selected_session = handoff["stdout_json"].get("session_id") or selected_session
if selected_session and not requested_session:
    selector[:] = ["--session-id", selected_session]
doctor = run_probe("doctor", ["doctor", "--diagnostics"])
probes.append(doctor)

passed = expected(handoff, exit_code=0, status="ok")
passed = passed and expected(doctor, exit_code=0, status="ok")
passed = passed and not doctor["stdout_json"].get("findings", [])
before = None
after = None
unchanged: dict[str, bool] = {}
session_status = handoff["stdout_json"].get("session_status")

if passed and selected_session:
    before = initial_before or snapshot(selected_session)
    if session_status != "active":
        state_path = Path(before["pointer_resolved"]) / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        outcome = state["status"].removeprefix("closed-")
        base_version = state["last_mutation"]["base_version"]
        reason = None
        if outcome == "abandoned":
            reason = next(
                item["summary"] for item in reversed(state["events"]) if item["kind"] == "abandoned"
            )

        close_args = [
            "close",
            "--expected-state-version",
            str(base_version),
            "--outcome",
            outcome,
        ]
        if reason is not None:
            close_args.extend(("--reason", reason))
        replay = run_probe("exact_close_replay", close_args)
        replay["typed_result"]["matches_stored_receipt"] = (
            replay["stdout_raw"] == canonical(state["last_mutation"]["receipt"]) + "\n"
            and replay["exit_code"] == 0
        )
        probes.append(replay)
        passed = passed and expected(replay, exit_code=0, status="ok")
        passed = passed and replay["typed_result"]["matches_stored_receipt"]

        current_version = state["state_version"]
        current_probes = [
            run_probe(
                "terminal_apply",
                ["apply", "--input", "-"],
                {"expected_state_version": current_version, "risk": "routine"},
            ),
            run_probe("terminal_next", ["next", "--expected-state-version", str(current_version)]),
        ]
        current_close = [
            "close",
            "--expected-state-version",
            str(current_version),
            "--outcome",
            outcome,
        ]
        if reason is not None:
            current_close.extend(("--reason", reason))
        current_probes.append(run_probe("terminal_close", current_close))
        probes.extend(current_probes)
        passed = passed and all(
            expected(item, exit_code=2, status="blocked", code="terminal_session")
            for item in current_probes
        )

        stale = run_probe(
            "stale_apply",
            ["apply", "--input", "-"],
            {"expected_state_version": base_version, "risk": "routine"},
        )
        probes.append(stale)
        passed = passed and expected(stale, exit_code=2, status="blocked", code="state_version_conflict")

    after = snapshot(selected_session)
    unchanged = {
        "pointer_target": before["pointer_target"] == after["pointer_target"],
        "pointer_resolved": before["pointer_resolved"] == after["pointer_resolved"],
        "generation_set": before["generation_set"] == after["generation_set"],
        "state_version": before["state_version"] == after["state_version"],
        "store_digest": before["store_digest"]["sha256"] == after["store_digest"]["sha256"],
    }
    passed = passed and all(unchanged.values())

receipt = {
    "schema_version": 1,
    "status": "pass" if passed else "fail",
    "captured_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "session_id": selected_session,
    "session_status": session_status,
    "accounting": {
        "projections": doctor["stdout_json"].get("diagnostics", {}).get("projections"),
        "reported_subagent_calls": reported_subagent_calls,
    },
    "probes": [
        {
            key: value
            for key, value in probe.items()
            if key in {"name", "argv", "input", "exit_code", "typed_result", "stderr"}
        }
        for probe in probes
    ],
    "before": before,
    "after": after,
    "unchanged": unchanged,
}

if json_output is not None:
    rdl_root = project_root / ".rdl"
    if json_output == rdl_root or rdl_root in json_output.parents:
        print("error: --json-output must not write inside .rdl", file=sys.stderr)
        raise SystemExit(1)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

print("RDL Dogfood Audit")
for probe in probes:
    typed = probe["typed_result"]
    label = typed.get("status", "error")
    if typed.get("code"):
        label += f" ({typed['code']})"
    print(f"{probe['name']}: {label}")
    findings = typed.get("findings", [])
    if findings:
        print("  findings: " + ", ".join(item.get("code", "unknown") for item in findings))
    if probe["stderr"]:
        print(f"  stderr: {probe['stderr']}")
if selected_session:
    print(f"  session: {selected_session}")
print(f"Audit: {'PASS' if passed else 'FAIL'}")
raise SystemExit(0 if passed else 1)
PY

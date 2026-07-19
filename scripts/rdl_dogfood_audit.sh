#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  echo "Usage: scripts/rdl_dogfood_audit.sh [--session-id <id>] <project-root>"
}

SESSION_ID=""
if [[ "${1:-}" == "--session-id" ]]; then
  [[ -n "${2:-}" ]] || { echo "error: --session-id requires a value" >&2; exit 1; }
  SESSION_ID="$2"
  shift 2
fi
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi
[[ "$#" -eq 1 ]] || { usage >&2; exit 1; }
[[ -d "$1" ]] || { echo "error: project root is not a directory" >&2; exit 1; }
PROJECT_ROOT="$(cd "$1" && pwd)"

selector=()
if [[ -n "${SESSION_ID}" ]]; then
  selector=(--session-id "${SESSION_ID}")
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

run_command() {
  local name="$1"
  shift
  set +e
  (
    cd "${PROJECT_ROOT}"
    "${ROOT_DIR}/local/research-dev-loop/bin/rdl" "$@" "${selector[@]}"
  ) >"${tmp_dir}/${name}.json" 2>"${tmp_dir}/${name}.err"
  echo "$?" >"${tmp_dir}/${name}.status"
  set -e
}

run_command handoff handoff
run_command doctor doctor

python3 - "${tmp_dir}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
failed = False
print("RDL Dogfood Audit")
for name in ("handoff", "doctor"):
    code = int((root / f"{name}.status").read_text(encoding="utf-8"))
    raw = (root / f"{name}.json").read_text(encoding="utf-8")
    diagnostic = (root / f"{name}.err").read_text(encoding="utf-8").strip()
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"status": "error", "code": "bootstrap_error" if diagnostic else "invalid_json"}
    print(f"{name}: {result.get('status', 'error')}")
    if result.get("session_id"):
        print(f"  session: {result['session_id']}")
    if result.get("code"):
        print(f"  code: {result['code']}")
    if diagnostic:
        print(f"  stderr: {diagnostic}")
    findings = result.get("findings", [])
    if findings:
        print("  findings: " + ", ".join(item.get("code", "unknown") for item in findings))
    failed = failed or code != 0 or result.get("status") != "ok" or bool(findings)
print(f"Audit: {'FAIL' if failed else 'PASS'}")
raise SystemExit(1 if failed else 0)
PY

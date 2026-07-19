#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDIT="${ROOT_DIR}/scripts/rdl_dogfood_audit.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

create_session() {
  local project_root="$1"
  local session_id="$2"
  PYTHONPATH="${ROOT_DIR}/local/research-dev-loop" python3 - "${project_root}" "${session_id}" <<'PY'
import sys
from pathlib import Path
from rdl import RdlEngine

root = Path(sys.argv[1])
RdlEngine(root).execute(
    "start",
    session_id=sys.argv[2],
    request={
        "mode": "research",
        "mission": {
            "objective": "dogfood fixture",
            "scope": ["fixture"],
            "out_of_scope": [],
            "success_criteria": ["state is recoverable"],
            "invariants": [],
            "abort_criteria": [],
        },
    },
)
PY
}

healthy="${tmp_dir}/healthy"
mkdir -p "${healthy}"
create_session "${healthy}" audit
"${AUDIT}" "${healthy}" >"${tmp_dir}/healthy.out"
grep -q "Audit: PASS" "${tmp_dir}/healthy.out" || fail "healthy session should pass"
grep -q "session: audit" "${tmp_dir}/healthy.out" || fail "audit should show selected session"

terminal="${tmp_dir}/terminal"
mkdir -p "${terminal}"
create_session "${terminal}" historical
PYTHONPATH="${ROOT_DIR}/local/research-dev-loop" python3 - "${terminal}" <<'PY'
import sys
from pathlib import Path
from rdl import RdlEngine

RdlEngine(Path(sys.argv[1])).execute(
    "close", session_id="historical", expected_state_version=1,
    outcome="abandoned", reason="fixture complete"
)
PY
"${AUDIT}" --session-id historical "${terminal}" >"${tmp_dir}/terminal.out"
grep -q "Audit: PASS" "${tmp_dir}/terminal.out" || fail "selected terminal session should pass"

empty="${tmp_dir}/empty"
mkdir -p "${empty}"
if "${AUDIT}" "${empty}" >"${tmp_dir}/empty.out"; then
  fail "empty project should fail"
fi
grep -q "no_active_session" "${tmp_dir}/empty.out" || fail "empty audit should explain failure"

generation="${healthy}/.rdl/sessions/audit"
echo "tampered" >"${generation}/progress.md"
if "${AUDIT}" "${healthy}" >"${tmp_dir}/drift.out"; then
  fail "derived view drift should fail strict dogfood audit"
fi
grep -q "derived_view_drift" "${tmp_dir}/drift.out" || fail "drift should be reported"

if "${AUDIT}" "${tmp_dir}/missing" >"${tmp_dir}/missing.out" 2>"${tmp_dir}/missing.err"; then
  fail "non-directory should fail"
fi
grep -q "project root is not a directory" "${tmp_dir}/missing.err" || fail "non-directory error missing"

broken_root="${tmp_dir}/broken-repo"
mkdir -p "${broken_root}/scripts" "${broken_root}/local/research-dev-loop/bin"
cp "${AUDIT}" "${broken_root}/scripts/rdl_dogfood_audit.sh"
cat >"${broken_root}/local/research-dev-loop/bin/rdl" <<'EOF'
#!/bin/sh
echo 'rdl bundled package is missing from the installed skill.' >&2
exit 1
EOF
chmod +x "${broken_root}/local/research-dev-loop/bin/rdl"
if "${broken_root}/scripts/rdl_dogfood_audit.sh" "${empty}" >"${tmp_dir}/bootstrap.out"; then
  fail "launcher bootstrap failure should fail"
fi
grep -q "bootstrap_error" "${tmp_dir}/bootstrap.out" || fail "bootstrap error code missing"
grep -q "bundled package is missing" "${tmp_dir}/bootstrap.out" || fail "bootstrap stderr missing"

echo "RDL dogfood audit ok"

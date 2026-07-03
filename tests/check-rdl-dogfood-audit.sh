#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDIT="${ROOT_DIR}/scripts/rdl_dogfood_audit.sh"
RDL_ENV="${ROOT_DIR}/local/research-dev-loop:${ROOT_DIR}/local/research-dev-loop/tests_py"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

run_rdl() {
  local project_root="$1"
  shift
  (
    cd "${project_root}"
    PYTHONPATH="${ROOT_DIR}/local/research-dev-loop" python3 -m rdl "$@" --json >/dev/null
  )
}

set_all_factors() {
  local project_root="$1"
  local section
  for section in \
    "Model or Algorithm" \
    "Dataset or Workload" \
    "Seed and Sampling" \
    "Hardware or Backend" \
    "Prompt or Policy Version" \
    "Baseline" \
    "Candidate-Visible Context" \
    "Metric Definition" \
    "Evaluator or Validator Version" \
    "Environment" \
    "Known Non-Determinism"
  do
    run_rdl "${project_root}" factors set --section "${section}" --value "fixture ${section}"
  done
}

create_complete_session() {
  local project_root="$1"
  PYTHONPATH="${RDL_ENV}" python3 - "${project_root}" <<'PY'
from pathlib import Path
import sys

from rdl_test_support import complete_research_round, create_session

session_dir = create_session(Path(sys.argv[1]), "audit_healthy")
complete_research_round(session_dir)
PY
}

create_incomplete_session() {
  local project_root="$1"
  PYTHONPATH="${RDL_ENV}" python3 - "${project_root}" <<'PY'
from pathlib import Path
import sys

from rdl_test_support import create_session

create_session(Path(sys.argv[1]), "audit_incomplete")
PY
}

assert_complete_session_passes() {
  local project_root="${tmp_dir}/healthy-project"
  mkdir -p "${project_root}"
  create_complete_session "${project_root}"

  run_rdl "${project_root}" memory --write
  run_rdl "${project_root}" progress active \
    --item coverage \
    --mode research \
    --text "fixture current focus" \
    --blocking no \
    --trigger "next fixture review"
  run_rdl "${project_root}" progress none --section Blocked --reason "no current blockers"
  run_rdl "${project_root}" progress none --section Deferred --reason "no deferred work"
  set_all_factors "${project_root}"

  if ! "${AUDIT}" "${project_root}" >"${tmp_dir}/healthy.out" 2>"${tmp_dir}/healthy.err"; then
    cat "${tmp_dir}/healthy.out" >&2
    cat "${tmp_dir}/healthy.err" >&2
    fail "healthy RDL session should pass dogfood audit"
  fi

  grep -q "Audit: PASS" "${tmp_dir}/healthy.out" \
    || fail "healthy audit output should report PASS"
  grep -q "handoff_status: ready" "${tmp_dir}/healthy.out" \
    || fail "healthy audit output should report ready handoff"
  grep -q "memory_status: healthy" "${tmp_dir}/healthy.out" \
    || fail "healthy audit output should report healthy memory"
  if grep -q "${project_root}" "${tmp_dir}/healthy.out"; then
    fail "audit output must not include the external project absolute path"
  fi
}

assert_incomplete_session_fails() {
  local project_root="${tmp_dir}/incomplete-project"
  mkdir -p "${project_root}"
  create_incomplete_session "${project_root}"

  if "${AUDIT}" "${project_root}" >"${tmp_dir}/incomplete.out" 2>"${tmp_dir}/incomplete.err"; then
    fail "incomplete RDL session should fail dogfood audit"
  fi

  grep -q "Audit: FAIL" "${tmp_dir}/incomplete.out" \
    || fail "incomplete audit output should report FAIL"
  grep -q "handoff_status: needs_attention" "${tmp_dir}/incomplete.out" \
    || fail "incomplete audit output should report needs_attention"
  grep -q "progress_gaps: Active, Blocked, Deferred" "${tmp_dir}/incomplete.out" \
    || fail "incomplete audit output should report manual progress gaps"
}

assert_empty_project_fails() {
  local project_root="${tmp_dir}/empty-project"
  mkdir -p "${project_root}"

  if "${AUDIT}" "${project_root}" >"${tmp_dir}/empty.out" 2>"${tmp_dir}/empty.err"; then
    fail "empty project should fail dogfood audit"
  fi

  grep -q "no_active_session" "${tmp_dir}/empty.out" \
    || fail "empty project audit should report no_active_session"
  grep -q "Audit: FAIL" "${tmp_dir}/empty.out" \
    || fail "empty project audit should report FAIL"
}

assert_non_directory_fails() {
  local bad_path="${tmp_dir}/not-a-directory"
  printf 'not a directory\n' >"${bad_path}"

  if "${AUDIT}" "${bad_path}" >"${tmp_dir}/bad.out" 2>"${tmp_dir}/bad.err"; then
    fail "non-directory path should fail dogfood audit"
  fi

  grep -q "project root is not a directory" "${tmp_dir}/bad.err" \
    || fail "non-directory audit should explain the parameter error"
}

assert_complete_session_passes
assert_incomplete_session_fails
assert_empty_project_fails
assert_non_directory_fails

echo "RDL dogfood audit ok"

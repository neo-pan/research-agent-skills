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

create_close_ready_session() {
  local project_root="$1"
  PYTHONPATH="${RDL_ENV}" python3 - "${project_root}" <<'PY'
from pathlib import Path
import sys

from test_cli_close import close_ready_session

close_ready_session(Path(sys.argv[1]), "negative")
PY
}

bind_close_review() {
  local project_root="$1"
  PYTHONPATH="${RDL_ENV}" python3 - "${project_root}" <<'PY'
from pathlib import Path
import sys

from rdl_test_support import bind_review_subject

bind_review_subject(Path(sys.argv[1]) / ".rdl" / "sessions" / "close_ok", "close")
PY
}

prepare_close_memory() {
  local project_root="$1"
  run_rdl "${project_root}" memory --write
  run_rdl "${project_root}" progress none --section Active --reason "close decision ready"
  run_rdl "${project_root}" progress none --section Blocked --reason "no current blockers"
  run_rdl "${project_root}" progress deferred \
    --item future-work \
    --reason "outside the closed mission" \
    --trigger "start a new reviewed mission"
  set_all_factors "${project_root}"
}

close_negative_session() {
  local project_root="$1"
  local output="$2"
  if ! (
    cd "${project_root}"
    PYTHONPATH="${ROOT_DIR}/local/research-dev-loop" python3 -m rdl close negative --json
  ) >"${output}.json" 2>"${output}.err"; then
    cat "${output}.json" >&2
    cat "${output}.err" >&2
    fail "close-ready fixture should close through the CLI"
  fi
}

mark_session_inactive() {
  local project_root="$1"
  local session_id="$2"
  PYTHONPATH="${RDL_ENV}" python3 - "${project_root}" "${session_id}" <<'PY'
from pathlib import Path
import sys

from rdl import integrity, store
from rdl.session import SessionStore

root = Path(sys.argv[1])
session_dir = root / ".rdl" / "sessions" / sys.argv[2]
state_path = session_dir / "state.json"
state = store.read_json(state_path)
state["status"] = "abandoned"
state["phase"] = "complete"
store.write_json_atomic(state_path, state)
integrity.refresh(SessionStore(root).load_session(session_dir))
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

assert_specified_session_path_passes_without_active_session() {
  local project_root="${tmp_dir}/specified-project"
  local session_path
  mkdir -p "${project_root}"
  create_complete_session "${project_root}"

  run_rdl "${project_root}" memory --write
  run_rdl "${project_root}" progress active \
    --item coverage \
    --text "fixture current focus" \
    --trigger "next fixture review"
  run_rdl "${project_root}" progress none --section Blocked --reason "no current blockers"
  run_rdl "${project_root}" progress none --section Deferred --reason "no deferred work"
  set_all_factors "${project_root}"
  mark_session_inactive "${project_root}" audit_healthy
  session_path="${project_root}/.rdl/sessions/audit_healthy"

  if ! "${AUDIT}" --session-path "${session_path}" "${project_root}" >"${tmp_dir}/specified.out" 2>"${tmp_dir}/specified.err"; then
    cat "${tmp_dir}/specified.out" >&2
    cat "${tmp_dir}/specified.err" >&2
    fail "specified inactive RDL session should pass dogfood audit"
  fi

  grep -q "Audit: PASS" "${tmp_dir}/specified.out" \
    || fail "specified audit output should report PASS"
  grep -q "review --pack: ok" "${tmp_dir}/specified.out" \
    || fail "specified audit output should include review pack"
  grep -q "session: audit_healthy" "${tmp_dir}/specified.out" \
    || fail "specified audit output should report the selected session"
  if grep -q "${project_root}" "${tmp_dir}/specified.out"; then
    fail "specified audit output must not include the external project absolute path"
  fi
}

assert_cli_closed_session_passes_action_aware_audit() {
  local project_root="${tmp_dir}/closed-project"
  local session_path
  mkdir -p "${project_root}"
  create_close_ready_session "${project_root}"

  prepare_close_memory "${project_root}"
  bind_close_review "${project_root}"
  close_negative_session "${project_root}" "${tmp_dir}/closed-transition"
  session_path="${project_root}/.rdl/sessions/close_ok"

  if ! "${AUDIT}" --session-path "${session_path}" "${project_root}" >"${tmp_dir}/closed.out" 2>"${tmp_dir}/closed.err"; then
    cat "${tmp_dir}/closed.out" >&2
    cat "${tmp_dir}/closed.err" >&2
    fail "CLI-closed RDL session should pass dogfood audit"
  fi

  grep -q "Audit: PASS" "${tmp_dir}/closed.out" \
    || fail "closed audit output should report PASS"
  grep -q "pack_action: close" "${tmp_dir}/closed.out" \
    || fail "closed audit should use the close review pack"
  grep -q "subject_binding: matched" "${tmp_dir}/closed.out" \
    || fail "closed audit should report matched close review binding"
}

assert_cli_closed_unbound_session_fails_audit() {
  local project_root="${tmp_dir}/closed-unbound-project"
  local session_path
  mkdir -p "${project_root}"
  create_close_ready_session "${project_root}"
  prepare_close_memory "${project_root}"
  close_negative_session "${project_root}" "${tmp_dir}/closed-unbound-transition"
  session_path="${project_root}/.rdl/sessions/close_ok"

  if "${AUDIT}" --session-path "${session_path}" "${project_root}" >"${tmp_dir}/closed-unbound.out" 2>"${tmp_dir}/closed-unbound.err"; then
    fail "new CLI-closed session with an unbound review should fail strict dogfood audit"
  fi

  grep -q "subject_binding: unbound" "${tmp_dir}/closed-unbound.out" \
    || fail "unbound closed audit should report the binding status"
  grep -q "Audit: FAIL" "${tmp_dir}/closed-unbound.out" \
    || fail "unbound closed audit should fail"
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

assert_ambiguous_selector_fails() {
  local project_root="${tmp_dir}/ambiguous-project"
  mkdir -p "${project_root}"

  if "${AUDIT}" --session-id one --session-path "${project_root}/.rdl/sessions/one" "${project_root}" >"${tmp_dir}/ambiguous.out" 2>"${tmp_dir}/ambiguous.err"; then
    fail "ambiguous session selector audit should fail"
  fi

  grep -q "pass either --session-id or --session-path, not both" "${tmp_dir}/ambiguous.err" \
    || fail "ambiguous selector audit should explain the parameter error"
}

assert_invalid_json_reports_sanitized_stderr() {
  local project_root="${tmp_dir}/invalid-json-project"
  local relative_project_root
  local wrapper_dir="${tmp_dir}/python-wrapper"
  local real_python
  mkdir -p "${project_root}" "${wrapper_dir}"
  relative_project_root="$(realpath --relative-to="${ROOT_DIR}" "${project_root}")"
  real_python="$(command -v python3)"

  cat >"${wrapper_dir}/python3" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "-m" && "${2:-}" == "rdl" ]]; then
  printf 'not-json\n'
  printf 'failure in %s/secret-session\n' "${AUDIT_TEST_PROJECT_ROOT}" >&2
  printf 'loader used %s/local/research-dev-loop\n' "${AUDIT_TEST_ROOT_DIR}" >&2
  printf 'temporary cache path=%s/audit-cache (%s/nested-cache)\n' "${AUDIT_TEST_TMP_DIR}" "${AUDIT_TEST_TMP_DIR}" >&2
  printf 'this fourth line should not be printed\n' >&2
  exit 17
fi

exec "${REAL_PYTHON}" "$@"
SH
  chmod +x "${wrapper_dir}/python3"

  if PATH="${wrapper_dir}:${PATH}" \
    REAL_PYTHON="${real_python}" \
    AUDIT_TEST_PROJECT_ROOT="${project_root}" \
    AUDIT_TEST_ROOT_DIR="${ROOT_DIR}" \
    AUDIT_TEST_TMP_DIR="${tmp_dir}" \
    "${AUDIT}" "${relative_project_root}" >"${tmp_dir}/invalid-json.out" 2>"${tmp_dir}/invalid-json.err"
  then
    fail "invalid JSON audit should fail"
  fi

  grep -q "invalid-json" "${tmp_dir}/invalid-json.out" \
    || fail "invalid JSON audit should report invalid-json"
  grep -q "exit: 17" "${tmp_dir}/invalid-json.out" \
    || fail "invalid JSON audit should report the failing exit code"
  grep -q "<project-root>/secret-session" "${tmp_dir}/invalid-json.out" \
    || fail "invalid JSON audit should sanitize project-root stderr"
  grep -q "<skill-pack-root>/local/research-dev-loop" "${tmp_dir}/invalid-json.out" \
    || fail "invalid JSON audit should sanitize skill-pack-root stderr"
  grep -q "<tmp-path>" "${tmp_dir}/invalid-json.out" \
    || fail "invalid JSON audit should sanitize temporary paths"
  if grep -q "this fourth line should not be printed" "${tmp_dir}/invalid-json.out"; then
    fail "invalid JSON stderr summary should be limited"
  fi
  if grep -q "${project_root}" "${tmp_dir}/invalid-json.out"; then
    fail "invalid JSON audit output must not include the external project absolute path"
  fi
  if grep -q "${ROOT_DIR}" "${tmp_dir}/invalid-json.out"; then
    fail "invalid JSON audit output must not include the skill-pack absolute path"
  fi
  if grep -q "${tmp_dir}" "${tmp_dir}/invalid-json.out"; then
    fail "invalid JSON audit output must not include temporary absolute paths"
  fi
}

assert_complete_session_passes
assert_specified_session_path_passes_without_active_session
assert_cli_closed_session_passes_action_aware_audit
assert_cli_closed_unbound_session_fails_audit
assert_incomplete_session_fails
assert_empty_project_fails
assert_non_directory_fails
assert_ambiguous_selector_fails
assert_invalid_json_reports_sanitized_stderr

echo "RDL dogfood audit ok"

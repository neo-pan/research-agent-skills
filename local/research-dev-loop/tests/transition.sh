#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RDL="${ROOT_DIR}/local/research-dev-loop/scripts/rdl.sh"
source "${ROOT_DIR}/local/research-dev-loop/tests/lib/rdl_fixtures.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_file_contains() {
  local file="$1"
  local pattern="$2"
  local relaxed
  local compact_colon
  relaxed="$(json_pattern "${pattern}")"
  compact_colon="${pattern//\": /\":}"
  grep -q "${pattern}" "${file}" || grep -q "${relaxed}" "${file}" || grep -q "${compact_colon}" "${file}" || fail "missing pattern ${pattern} in ${file}"
}

json_pattern() {
  printf '%s' "$1" | sed -e 's#": "#": *"#g'
}

assert_file_absent() {
  [[ ! -e "$1" ]] || fail "unexpected file exists: $1"
}

complete_review() {
  local file="$1"
  local recommended="${2:-continue}"
  rdl_write_complete_review "${file}" "${recommended}"
}

complete_decision() {
  local file="$1"
  local decision="$2"
  local closes="$3"
  local next_loop="${4:-none}"
  rdl_write_complete_decision "${file}" "${decision}" "${closes}" "${next_loop}" "continue same mode" "E1 fixture evidence"
}

complete_manifest() {
  local file="$1"
  rdl_write_artifact_manifest "${file}" E1 artifacts/check.log "Fixture transition evidence"
}

complete_research_records() {
  local round_dir="$1"
  rdl_write_research_evidence "${round_dir}" yes
}

complete_final_report() {
  local file="$1"
  local outcome="$2"
  rdl_write_final_report "${file}" "${outcome}" "Fixture claim."
}

write_ready_progress() {
  local file="$1"
  rdl_write_ready_progress "${file}" no
}

start_research_repo() {
  local repo="$1"
  local session_id="$2"
  mkdir -p "${repo}"
  cat > "${repo}/mission.md" <<'MISSION'
# Mission

Transition fixture mission.
MISSION
  cd "${repo}"
  "${RDL}" start research mission.md --session-id "${session_id}" > start.json
}

tmp_root="$(mktemp -d)"
trap 'rm -rf "${tmp_root}"' EXIT

repo_next="${tmp_root}/next"
start_research_repo "${repo_next}" transition_next
"${RDL}" review > /dev/null
complete_review .rdl/sessions/transition_next/rounds/001/review.md
"${RDL}" decide continue > /dev/null
complete_decision .rdl/sessions/transition_next/rounds/001/decision.md continue claim build
complete_research_records .rdl/sessions/transition_next/rounds/001
complete_manifest .rdl/sessions/transition_next/artifact-manifest.json
"${RDL}" next > next.json
assert_file_contains next.json '"status": "ok"'
assert_file_contains next.json '"phase": "plan"'
assert_file_contains next.json '"round": 2'
[[ -f .rdl/sessions/transition_next/rounds/002/prompt.md ]] || fail "next prompt was not created"
assert_file_contains .rdl/sessions/transition_next/state.json '"round": 2'
assert_file_contains .rdl/sessions/transition_next/state.json '"phase": "plan"'
assert_file_contains .rdl/sessions/transition_next/decision-ledger.md '## Round 1 Decision'
assert_file_contains .rdl/sessions/transition_next/decision-ledger.md 'Next round: 002'
"${RDL}" review > review-next.json
assert_file_contains review-next.json '"status": "ok"'
assert_file_contains review-next.json 'rounds/002/review.md'

repo_close="${tmp_root}/close"
start_research_repo "${repo_close}" transition_close
"${RDL}" review > /dev/null
complete_review .rdl/sessions/transition_close/rounds/001/review.md close-positive
"${RDL}" decide close-positive > /dev/null
complete_decision .rdl/sessions/transition_close/rounds/001/decision.md close-positive claim none
complete_research_records .rdl/sessions/transition_close/rounds/001
complete_manifest .rdl/sessions/transition_close/artifact-manifest.json
complete_final_report .rdl/sessions/transition_close/final-report.md positive
write_ready_progress .rdl/sessions/transition_close/progress.md
"${RDL}" close positive > close.json
assert_file_contains close.json '"status": "ok"'
assert_file_contains close.json '"phase": "complete"'
assert_file_contains close.json '"next_action": "closed-positive"'
assert_file_contains .rdl/sessions/transition_close/state.json '"status": "closed-positive"'
assert_file_contains .rdl/sessions/transition_close/decision-ledger.md '## Session Closed'

repo_guard="${tmp_root}/guard-close"
start_research_repo "${repo_guard}" transition_guard
"${RDL}" review > /dev/null
complete_review .rdl/sessions/transition_guard/rounds/001/review.md close-positive
"${RDL}" decide close-positive > /dev/null
complete_decision .rdl/sessions/transition_guard/rounds/001/decision.md close-positive claim none
complete_research_records .rdl/sessions/transition_guard/rounds/001
complete_manifest .rdl/sessions/transition_guard/artifact-manifest.json
complete_final_report .rdl/sessions/transition_guard/final-report.md positive
write_ready_progress .rdl/sessions/transition_guard/progress.md
"${RDL}" guard-stop --guard-session-id transition_guard --guard-command-id cmd-1 > guard.json
assert_file_contains guard.json '"status": "ok"'
assert_file_contains guard.json '"action": "guard-stop"'
assert_file_contains guard.json '"phase": "complete"'
assert_file_contains guard.json '"next_action": "closed-positive"'
assert_file_contains .rdl/sessions/transition_guard/state.json '"status": "closed-positive"'
assert_file_absent .rdl/sessions/transition_guard/rounds/002

repo_abandon="${tmp_root}/abandon"
start_research_repo "${repo_abandon}" transition_abandon
"${RDL}" abandon operator stopped duplicate effort > abandon.json
assert_file_contains abandon.json '"status": "ok"'
assert_file_contains abandon.json '"phase": "complete"'
assert_file_contains abandon.json '"next_action": "abandoned"'
assert_file_contains .rdl/sessions/transition_abandon/state.json '"status": "abandoned"'
assert_file_contains .rdl/sessions/transition_abandon/decision-ledger.md '## Session Abandoned'
assert_file_contains .rdl/sessions/transition_abandon/decision-ledger.md 'Scientific outcome claimed: none'
assert_file_contains .rdl/sessions/transition_abandon/progress.md '## Abandon Record'
assert_file_contains .rdl/sessions/transition_abandon/progress.md 'operator stopped duplicate effort'

echo "transition tests ok"

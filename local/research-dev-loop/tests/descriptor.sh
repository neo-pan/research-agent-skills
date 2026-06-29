#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RDL="${ROOT_DIR}/local/research-dev-loop/scripts/rdl.sh"
source "${ROOT_DIR}/local/research-dev-loop/tests/lib/rdl_fixtures.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_file() {
  [[ -f "$1" ]] || fail "missing file: $1"
}

assert_contains() {
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

assert_fails() {
  local output="$1"
  shift
  if "$@" > "${output}"; then
    fail "command unexpectedly succeeded: $*"
  fi
}

assert_file_has_fields() {
  local file="$1"
  shift
  local field
  for field in "$@"; do
    assert_contains "${file}" "^${field}:"
  done
}

assert_file_has_sections() {
  local file="$1"
  shift
  local section
  for section in "$@"; do
    assert_contains "${file}" "^## ${section}$"
  done
}

remove_integrity_entry() {
  local manifest="$1"
  local path="$2"
  python3 - "${manifest}" "${path}" <<'PY'
import json
import sys

manifest, removed_path = sys.argv[1], sys.argv[2]
with open(manifest, "r", encoding="utf-8") as fh:
    data = json.load(fh)

data["entries"] = [
    entry for entry in data["entries"]
    if entry.get("path") != removed_path
]

with open(manifest, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

write_incomplete_review() {
  local file="$1"
  cat > "${file}" <<'REVIEW'
# Review

Reviewer: fixture
Review Mode: manual
Review Scope: current round
Artifacts Reviewed: prompt
Verdict: PASS
Decision Reviewed: pending
Evidence Reviewed: fixture evidence
Blocking Evidence Gaps: none
Implementation Findings: none
Evaluation Integrity Findings: acceptable
Overclaim Risks: bounded
Readiness Level: ready
Recommended Decision:

REVIEW
}

write_incomplete_decision() {
  local file="$1"
  cat > "${file}" <<'DECISION'
# Decision

Decision: continue
Closes: claim
Evidence:
Uncertainty: bounded
What this rules out: unsupported alternatives
What remains unknown: later work
Recommended next loop: none
Next smallest step: continue same mode

DECISION
}

tmp_root="$(mktemp -d)"
trap 'rm -rf "${tmp_root}"' EXIT

fixture_dir="${tmp_root}/helper-fixtures"
mkdir -p "${fixture_dir}/rounds/001" "${fixture_dir}/build-round"
rdl_write_complete_review "${fixture_dir}/review.md" close-positive PASS "close decision"
rdl_write_complete_decision "${fixture_dir}/decision.md" close-positive claim none "close the session" "E1 fixture evidence"
rdl_write_research_evidence "${fixture_dir}/rounds/001" yes
rdl_write_build_evidence "${fixture_dir}/build-round" yes
rdl_write_artifact_manifest "${fixture_dir}/artifact-manifest.json"
rdl_write_final_report "${fixture_dir}/final-report.md" positive "fixture claim"
rdl_write_ready_progress "${fixture_dir}/progress.md" yes
assert_file_has_fields "${fixture_dir}/review.md" \
  Reviewer "Review Mode" "Review Scope" "Artifacts Reviewed" Verdict \
  "Decision Reviewed" "Evidence Reviewed" "Blocking Evidence Gaps" \
  "Implementation Findings" "Evaluation Integrity Findings" "Overclaim Risks" \
  "Readiness Level" "Recommended Decision"
assert_file_has_fields "${fixture_dir}/decision.md" \
  Decision Closes Evidence Uncertainty "What this rules out" \
  "What remains unknown" "Recommended next loop" "Next smallest step"
assert_file_has_sections "${fixture_dir}/final-report.md" \
  Outcome "Claim or Capability Closed" "Evidence Cited" \
  "Missing Evidence and Confounders" "Negative, Null, or Inconclusive Results" \
  "Open Questions" "Deferred Items" "Reusable Lessons" "Close Checklist"
assert_file_has_sections "${fixture_dir}/progress.md" \
  Active Completed Blocked Deferred "Open Questions"
assert_file "${fixture_dir}/rounds/001/evidence.md"
assert_file "${fixture_dir}/rounds/001/interpretation.md"
assert_file "${fixture_dir}/build-round/intent.md"
assert_file "${fixture_dir}/build-round/work.md"
assert_file "${fixture_dir}/build-round/evidence.md"

repo="${tmp_root}/descriptor"
mkdir -p "${repo}"
cat > "${repo}/mission.md" <<'MISSION'
# Mission

Descriptor fixture mission.
MISSION

cd "${repo}"
"${RDL}" start research mission.md --session-id descriptor_research > start.json
assert_contains start.json '"status": "ok"'

session_dir=".rdl/sessions/descriptor_research"
assert_file "${session_dir}/state.json"
assert_file "${session_dir}/mission.md"
assert_file "${session_dir}/factors.md"
assert_file "${session_dir}/artifact-manifest.json"
assert_file "${session_dir}/decision-ledger.md"
assert_file "${session_dir}/progress.md"
assert_file "${session_dir}/rounds/001/prompt.md"

assert_contains "${session_dir}/integrity.json" '"path": "state.json"'
assert_contains "${session_dir}/integrity.json" '"policy": "cli_owned"'
assert_contains "${session_dir}/integrity.json" '"path": "decision-ledger.md"'
assert_contains "${session_dir}/integrity.json" '"policy": "append_only"'
assert_contains "${session_dir}/integrity.json" '"path": "rounds/001/prompt.md"'
assert_contains "${session_dir}/integrity.json" '"policy": "managed_prefix"'
assert_contains "${session_dir}/integrity.json" '"path": "mission.md"'
assert_contains "${session_dir}/integrity.json" '"policy": "human_owned"'

repo_helper_cli="${tmp_root}/helper-cli"
mkdir -p "${repo_helper_cli}"
cat > "${repo_helper_cli}/mission.md" <<'MISSION'
# Mission

Descriptor helper CLI fixture.
MISSION

cd "${repo_helper_cli}"
"${RDL}" start research mission.md --session-id descriptor_helper_cli > /dev/null
"${RDL}" review > /dev/null
"${RDL}" decide close-positive > /dev/null
rdl_write_complete_review ".rdl/sessions/descriptor_helper_cli/rounds/001/review.md" close-positive PASS "close decision"
rdl_write_complete_decision ".rdl/sessions/descriptor_helper_cli/rounds/001/decision.md" close-positive claim none "close the session" "E1 fixture evidence"
rdl_write_research_evidence ".rdl/sessions/descriptor_helper_cli/rounds/001" yes
rdl_write_artifact_manifest ".rdl/sessions/descriptor_helper_cli/artifact-manifest.json"
rdl_write_final_report ".rdl/sessions/descriptor_helper_cli/final-report.md" positive "fixture claim"
rdl_write_ready_progress ".rdl/sessions/descriptor_helper_cli/progress.md" yes
"${RDL}" close positive > helper-close.json
assert_contains helper-close.json '"status": "ok"'
assert_contains helper-close.json '"phase": "complete"'

repo_nested="${tmp_root}/nested-round-path"
mkdir -p "${repo_nested}"
cat > "${repo_nested}/mission.md" <<'MISSION'
# Mission

Descriptor nested path fixture.
MISSION

cd "${repo_nested}"
"${RDL}" start research mission.md --session-id descriptor_nested > /dev/null
mkdir -p ".rdl/sessions/descriptor_nested/rounds/001/nested"
printf '# Nested Prompt\n' > ".rdl/sessions/descriptor_nested/rounds/001/nested/prompt.md"
"${RDL}" doctor > doctor-nested-round-path.json || true
if grep -q '"file":"rounds/001/nested/prompt.md"' doctor-nested-round-path.json; then
  fail "nested round prompt must not be treated as expected protocol state"
fi

repo_unknown_round="${tmp_root}/unknown-round-file"
mkdir -p "${repo_unknown_round}"
cat > "${repo_unknown_round}/mission.md" <<'MISSION'
# Mission

Descriptor unknown round file fixture.
MISSION

cd "${repo_unknown_round}"
"${RDL}" start research mission.md --session-id descriptor_unknown_round > /dev/null
printf 'not a protocol file\n' > ".rdl/sessions/descriptor_unknown_round/rounds/001/notes.md"
"${RDL}" doctor > doctor-unknown-round-file.json || true
if grep -q '"file":"rounds/001/notes.md"' doctor-unknown-round-file.json; then
  fail "unknown round file must not be treated as expected protocol state"
fi

repo_missing="${tmp_root}/missing-protected-entry"
mkdir -p "${repo_missing}"
cat > "${repo_missing}/mission.md" <<'MISSION'
# Mission

Descriptor missing protected entry fixture.
MISSION

cd "${repo_missing}"
"${RDL}" start research mission.md --session-id descriptor_missing > /dev/null
remove_integrity_entry ".rdl/sessions/descriptor_missing/integrity.json" "rounds/001/prompt.md"
assert_fails doctor-missing-prompt-entry.json "${RDL}" doctor
assert_contains doctor-missing-prompt-entry.json '"code":"missing_integrity_entry"'
assert_contains doctor-missing-prompt-entry.json '"file":"rounds/001/prompt.md"'

repo_review="${tmp_root}/missing-review-field"
mkdir -p "${repo_review}"
cat > "${repo_review}/mission.md" <<'MISSION'
# Mission

Descriptor required field fixture.
MISSION

cd "${repo_review}"
"${RDL}" start research mission.md --session-id descriptor_review > /dev/null
"${RDL}" review > /dev/null
write_incomplete_review ".rdl/sessions/descriptor_review/rounds/001/review.md"
assert_fails doctor-missing-review-field.json "${RDL}" doctor
assert_contains doctor-missing-review-field.json '"code":"missing_review_field"'
assert_contains doctor-missing-review-field.json 'review.md#Recommended Decision'

repo_decision="${tmp_root}/missing-decision-field"
mkdir -p "${repo_decision}"
cat > "${repo_decision}/mission.md" <<'MISSION'
# Mission

Descriptor decision field fixture.
MISSION

cd "${repo_decision}"
"${RDL}" start research mission.md --session-id descriptor_decision > /dev/null
"${RDL}" decide continue > /dev/null
write_incomplete_decision ".rdl/sessions/descriptor_decision/rounds/001/decision.md"
assert_fails doctor-missing-decision-field.json "${RDL}" doctor
assert_contains doctor-missing-decision-field.json '"code":"missing_decision_field"'
assert_contains doctor-missing-decision-field.json 'decision.md#Evidence'

repo_progress="${tmp_root}/missing-progress-section"
mkdir -p "${repo_progress}"
cat > "${repo_progress}/mission.md" <<'MISSION'
# Mission

Descriptor progress section fixture.
MISSION

cd "${repo_progress}"
"${RDL}" start research mission.md --session-id descriptor_progress > /dev/null
sed -i '/^## Open Questions$/,$d' ".rdl/sessions/descriptor_progress/progress.md"
assert_fails doctor-missing-progress-section.json "${RDL}" doctor
assert_contains doctor-missing-progress-section.json '"code":"missing_progress_section"'
assert_contains doctor-missing-progress-section.json 'progress.md#Open Questions'

echo "descriptor tests ok"

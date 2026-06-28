#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RDL="${ROOT_DIR}/local/research-dev-loop/scripts/rdl.sh"

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
  grep -q "${pattern}" "${file}" || fail "missing pattern ${pattern} in ${file}"
}

assert_fails() {
  local output="$1"
  shift
  if "$@" > "${output}"; then
    fail "command unexpectedly succeeded: $*"
  fi
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

assert_contains "${session_dir}/integrity.json" '"path":"state.json","policy":"cli_owned"'
assert_contains "${session_dir}/integrity.json" '"path":"decision-ledger.md","policy":"append_only"'
assert_contains "${session_dir}/integrity.json" '"path":"rounds/001/prompt.md","policy":"managed_prefix"'
assert_contains "${session_dir}/integrity.json" '"path":"mission.md","policy":"human_owned"'

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
assert_contains doctor-missing-review-field.json '"file":".rdl/sessions/descriptor_review/rounds/001/review.md#Recommended Decision"'

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
assert_contains doctor-missing-decision-field.json '"file":".rdl/sessions/descriptor_decision/rounds/001/decision.md#Evidence"'

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
assert_contains doctor-missing-progress-section.json '"file":"progress.md#Open Questions"'

echo "descriptor tests ok"

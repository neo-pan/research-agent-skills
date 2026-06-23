#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RDL="${ROOT_DIR}/local/research-dev-loop/scripts/rdl.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_file_contains() {
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

with_manifest() {
  local manifest="$1"
  local script="$2"
  local target_file="${3:-}"
  python3 - "${manifest}" "${script}" "${target_file}" <<'PY'
import hashlib
import json
import sys

manifest, script, target_file = sys.argv[1], sys.argv[2], sys.argv[3]
with open(manifest, "r", encoding="utf-8") as fh:
    data = json.load(fh)

entries = data["entries"]
if script == "empty":
    data["entries"] = []
elif script == "remove-state":
    data["entries"] = [entry for entry in entries if entry.get("path") != "state.json"]
elif script == "remove-evidence":
    data["entries"] = [entry for entry in entries if entry.get("path") != "rounds/001/evidence.md"]
elif script == "duplicate-state":
    state_entry = next(entry for entry in entries if entry.get("path") == "state.json")
    data["entries"].append(dict(state_entry))
elif script == "state-policy-human":
    for entry in entries:
        if entry.get("path") == "state.json":
            entry["policy"] = "human_owned"
elif script == "state-policy-human-current-hash":
    with open(target_file, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    for entry in entries:
        if entry.get("path") == "state.json":
            entry["policy"] = "human_owned"
            entry["sha256"] = digest
elif script == "unknown-path":
    data["entries"].append({
        "path": "project-output.log",
        "policy": "human_owned",
        "sha256": "0" * 64,
    })
elif script == "traversal-path":
    with open(target_file, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    data["entries"].append({
        "path": "rounds/001/../../../../outside/evidence.md",
        "policy": "human_owned",
        "sha256": digest,
    })
else:
    raise SystemExit(f"unknown manifest script: {script}")

with open(manifest, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
}

prepare_manifest_repo() {
  local repo_dir="$1"
  local session_id="$2"
  local mission_source="${3:-mission.md}"
  mkdir -p "${repo_dir}"
  cat > "${repo_dir}/${mission_source}" <<'MISSION'
# Mission

Manifest fixture mission.
MISSION
  cd "${repo_dir}"
  "${RDL}" start research "${mission_source}" --session-id "${session_id}" > /dev/null
}

break_integrity_manifest() {
  local session_dir="$1"
  local mode="$2"
  case "${mode}" in
    empty)
      with_manifest "${session_dir}/integrity.json" empty
      ;;
    bad)
      printf '{ broken\n' > "${session_dir}/integrity.json"
      ;;
    *)
      fail "unknown break_integrity_manifest mode ${mode}"
      ;;
  esac
}

complete_guard_review() {
  local file="$1"
  cat > "${file}" <<'REVIEW'
# Review

Reviewer: fixture
Review Mode: manual
Review Scope: current round
Artifacts Reviewed: prompt, evidence, decision
Verdict: PASS
Decision Reviewed: pending
Evidence Reviewed: fixture evidence
Blocking Evidence Gaps: none
Implementation Findings: none
Evaluation Integrity Findings: acceptable
Overclaim Risks: bounded
Readiness Level: ready
Recommended Decision: continue

REVIEW
}

complete_guard_decision() {
  local file="$1"
  cat > "${file}" <<'DECISION'
# Decision

Decision: continue
Closes: claim
Evidence: fixture evidence
Uncertainty: bounded
What this rules out: unsupported alternatives
What remains unknown: later work
Recommended next loop: none
Next smallest step: continue same mode

DECISION
}

complete_guard_research_records() {
  local round_dir="$1"
  cat > "${round_dir}/evidence.md" <<'EVIDENCE'
# Evidence

Research evidence: fixture claim evidence.
EVIDENCE
  cat > "${round_dir}/interpretation.md" <<'INTERPRETATION'
# Interpretation

Interpretation: fixture evidence supports the next research step.
INTERPRETATION
}

complete_guard_close_research_records() {
  local round_dir="$1"
  cat > "${round_dir}/evidence.md" <<'EVIDENCE'
# Evidence

## Claim Under Review

Fixture claim.

## Evidence Artifacts

| ID | Kind | Path or URL | Supports | Notes |
|---|---|---|---|---|
| E1 | log | artifacts/check.log | claim | fixture evidence cited |

## Evaluation Integrity

Manual fixture integrity reviewed.

## Missing Evidence

No blocking missing evidence for this fixture.

## Known Confounders

No known blocking confounders.

## Evidence Budget

One local fixture check.
EVIDENCE
  cat > "${round_dir}/interpretation.md" <<'INTERPRETATION'
# Interpretation

Interpretation: fixture evidence supports closing the claim.
INTERPRETATION
}

complete_guard_build_records() {
  local round_dir="$1"
  local verification="${2:-yes}"
  cat > "${round_dir}/intent.md" <<'INTENT'
# Intent

Intent: build the fixture capability.
INTENT
  cat > "${round_dir}/work.md" <<'WORK'
# Work

Work completed: fixture implementation change.
WORK
  if [[ "${verification}" == "yes" ]]; then
    cat > "${round_dir}/evidence.md" <<'EVIDENCE'
# Evidence

Verification evidence: fixture capability check passed.
EVIDENCE
  else
    cat > "${round_dir}/evidence.md" <<'EVIDENCE'
# Evidence

Evidence exists but no verification is recorded.
EVIDENCE
  fi
}

complete_guard_build_decision() {
  local file="$1"
  cat > "${file}" <<'DECISION'
# Decision

Decision: accept
Closes: capability
Evidence: fixture evidence
Uncertainty: bounded
What this rules out: unsupported alternatives
What remains unknown: later work
Recommended next loop: none
Next smallest step: continue same mode

DECISION
}

complete_guard_close_decision() {
  local file="$1"
  cat > "${file}" <<'DECISION'
# Decision

Decision: close-positive
Closes: claim
Evidence: E1 fixture evidence
Uncertainty: bounded
What this rules out: unsupported alternatives
What remains unknown: later work
Recommended next loop: none
Next smallest step: close the session

DECISION
}

complete_guard_manifest() {
  local file="$1"
  cat > "${file}" <<'MANIFEST'
{
  "artifacts": [
    {
      "id": "E1",
      "kind": "log",
      "path": "artifacts/check.log"
    }
  ]
}
MANIFEST
}

complete_guard_final_report() {
  local file="$1"
  cat > "${file}" <<'REPORT'
# Final Report

## Outcome

positive

## Claim or Capability Closed

fixture claim

## Evidence Cited

E1 fixture evidence.

## Missing Evidence and Confounders

No blocking missing evidence or confounders remain for this fixture.

## Negative, Null, or Inconclusive Results

None beyond the selected close outcome.

## Open Questions

No blocking open questions remain.

## Deferred Items

Deferred fixture follow-up has a revisit trigger.

## Reusable Lessons

No reusable lesson.

## Close Checklist

- [x] Final decision is positive, negative, or inconclusive.
- [x] Claim or capability closed is named.
- [x] Evidence artifacts are cited.
- [x] Missing evidence and known confounders are retained.
- [x] Negative, null, or inconclusive results are preserved.
- [x] Open questions are answered or carried forward explicitly.
- [x] Deferred items have revisit triggers.
REPORT
}

write_guard_ready_progress() {
  local file="$1"
  cat > "${file}" <<'PROGRESS'
# Progress

## Active

| Item | Mode | Claim or Capability | Blocking? | Next Review Trigger |
|---|---|---|---|---|

## Completed

| Item | Decision | Evidence | Round |
|---|---|---|---|

## Blocked

| Item | Reason | Needed Evidence or Input | Decision Impact |
|---|---|---|---|

## Deferred

| Item | Reason | Revisit Trigger |
|---|---|---|
| Follow-up calibration | not needed for close | next benchmark expansion |

## Open Questions

| Question | Owner | Blocking? | Resolution |
|---|---|---|---|
| Is release timing known? | fixture | no | Non-blocking follow-up. |
PROGRESS
}

write_guard_blocking_question_progress() {
  local file="$1"
  write_guard_ready_progress "${file}"
  cat >> "${file}" <<'PROGRESS'
| Is the claim still uncertain? | fixture | yes | - |
PROGRESS
}

write_guard_bad_deferred_progress() {
  local file="$1"
  cat > "${file}" <<'PROGRESS'
# Progress

## Active

| Item | Mode | Claim or Capability | Blocking? | Next Review Trigger |
|---|---|---|---|---|

## Completed

| Item | Decision | Evidence | Round |
|---|---|---|---|

## Blocked

| Item | Reason | Needed Evidence or Input | Decision Impact |
|---|---|---|---|

## Deferred

| Item | Reason | Revisit Trigger |
|---|---|---|
| Follow-up fixture | - | - |

## Open Questions

| Question | Owner | Blocking? | Resolution |
|---|---|---|---|
PROGRESS
}

prepare_guard_close_repo() {
  local repo_dir="$1"
  local session_id="$2"
  prepare_manifest_repo "${repo_dir}" "${session_id}"
  complete_guard_review ".rdl/sessions/${session_id}/rounds/001/review.md"
  complete_guard_close_decision ".rdl/sessions/${session_id}/rounds/001/decision.md"
  complete_guard_close_research_records ".rdl/sessions/${session_id}/rounds/001"
  complete_guard_manifest ".rdl/sessions/${session_id}/artifact-manifest.json"
  write_guard_ready_progress ".rdl/sessions/${session_id}/progress.md"
}

assert_repair_blocks_after_manifest_break() {
  local repo_dir="$1"
  local session_id="$2"
  local break_mode="$3"
  local changed_file="$4"
  local expected_code="$5"
  prepare_manifest_repo "${repo_dir}" "${session_id}"
  case "${changed_file}" in
    state.json)
      sed -i 's/"phase": "plan"/"phase": "work"/' ".rdl/sessions/${session_id}/state.json"
      ;;
    mission.md)
      printf '\nChanged mission.\n' >> ".rdl/sessions/${session_id}/mission.md"
      ;;
    rounds/001/evidence.md)
      cat > ".rdl/sessions/${session_id}/rounds/001/evidence.md" <<'EVIDENCE'
# Evidence

Changed evidence.
EVIDENCE
      ;;
    rounds/001/decision.md)
      complete_guard_decision ".rdl/sessions/${session_id}/rounds/001/decision.md"
      ;;
    rounds/001/review.md)
      complete_guard_review ".rdl/sessions/${session_id}/rounds/001/review.md"
      ;;
    final-report.md)
      complete_guard_final_report ".rdl/sessions/${session_id}/final-report.md"
      ;;
    *)
      fail "unknown changed file ${changed_file}"
      ;;
  esac
  break_integrity_manifest ".rdl/sessions/${session_id}" "${break_mode}"
  assert_fails "repair-${session_id}.json" "${RDL}" repair
  assert_file_contains "repair-${session_id}.json" '"status": "error"'
  assert_file_contains "repair-${session_id}.json" "\"code\":\"${expected_code}\""
  if [[ "${expected_code}" == "unsafe_integrity_manifest" ]]; then
    assert_file_contains "repair-${session_id}.json" '"file":"integrity.json"'
  else
    assert_file_contains "repair-${session_id}.json" "\"file\":\"${changed_file}\""
  fi
}

assert_repair_blocks_missing_protocol_file() {
  local repo_dir="$1"
  local session_id="$2"
  local missing_file="$3"
  prepare_manifest_repo "${repo_dir}" "${session_id}"
  rm ".rdl/sessions/${session_id}/${missing_file}"
  assert_fails "repair-${session_id}.json" "${RDL}" repair
  assert_file_contains "repair-${session_id}.json" '"status": "blocked"'
  assert_file_contains "repair-${session_id}.json" '"code":"unsafe_missing_protocol_file"'
  assert_file_contains "repair-${session_id}.json" "\"file\":\"${missing_file}\""
}

tmp_root="$(mktemp -d)"
trap 'rm -rf "${tmp_root}"' EXIT

repo="${tmp_root}/repo"
mkdir -p "${repo}"
cat > "${repo}/mission.md" <<'MISSION'
# Mission

Round 1 fixture mission.
MISSION

cd "${repo}"

assert_fails missing-session-id.json "${RDL}" start research mission.md --session-id
assert_file_contains missing-session-id.json '"status": "error"'
assert_file_contains missing-session-id.json '"code":"missing_session_id"'
assert_file_contains missing-session-id.json '"blockers": \['

assert_fails status-bogus.json "${RDL}" status --bogus
assert_file_contains status-bogus.json '"status": "error"'
assert_file_contains status-bogus.json '"code":"unknown_option"'

"${RDL}" start research mission.md --session-id r1 > start.json
"${RDL}" doctor > doctor-ok.json
assert_file_contains doctor-ok.json '"status": "ok"'
assert_file_contains doctor-ok.json '"action": "doctor"'
assert_file_contains doctor-ok.json '"session_id": "r1"'
assert_file_contains doctor-ok.json '"blockers": \[\]'

sed -i 's/"mode": "research"/"mode": "build"/' .rdl/sessions/r1/state.json
assert_fails doctor-state-integrity.json "${RDL}" doctor
assert_file_contains doctor-state-integrity.json '"status": "error"'
assert_file_contains doctor-state-integrity.json '"code":"integrity_violation_cli_owned"'
assert_file_contains doctor-state-integrity.json '"file":"state.json"'
sed -i 's/"mode": "build"/"mode": "research"/' .rdl/sessions/r1/state.json

repo_empty_manifest="${tmp_root}/empty-manifest"
prepare_manifest_repo "${repo_empty_manifest}" empty_manifest
with_manifest .rdl/sessions/empty_manifest/integrity.json empty
assert_fails doctor-empty-integrity.json "${RDL}" doctor
assert_file_contains doctor-empty-integrity.json '"status": "error"'
assert_file_contains doctor-empty-integrity.json '"code":"empty_integrity_manifest"'
sed -i 's/"phase": "plan"/"phase": "work"/' .rdl/sessions/empty_manifest/state.json
assert_fails doctor-empty-integrity-edited-state.json "${RDL}" doctor
assert_file_contains doctor-empty-integrity-edited-state.json '"status": "error"'
assert_file_contains doctor-empty-integrity-edited-state.json '"code":"empty_integrity_manifest"'

repo_missing_state_entry="${tmp_root}/missing-state-entry"
prepare_manifest_repo "${repo_missing_state_entry}" missing_state_entry
with_manifest .rdl/sessions/missing_state_entry/integrity.json remove-state
assert_fails doctor-missing-state-entry.json "${RDL}" doctor
assert_file_contains doctor-missing-state-entry.json '"status": "error"'
assert_file_contains doctor-missing-state-entry.json '"code":"missing_integrity_entry"'
assert_file_contains doctor-missing-state-entry.json '"file":"state.json"'
sed -i 's/"phase": "plan"/"phase": "work"/' .rdl/sessions/missing_state_entry/state.json
assert_fails doctor-missing-state-entry-edited-state.json "${RDL}" doctor
assert_file_contains doctor-missing-state-entry-edited-state.json '"status": "error"'
assert_file_contains doctor-missing-state-entry-edited-state.json '"code":"missing_integrity_entry"'

repo_duplicate_state_entry="${tmp_root}/duplicate-state-entry"
prepare_manifest_repo "${repo_duplicate_state_entry}" duplicate_state_entry
with_manifest .rdl/sessions/duplicate_state_entry/integrity.json duplicate-state
assert_fails doctor-duplicate-state-entry.json "${RDL}" doctor
assert_file_contains doctor-duplicate-state-entry.json '"status": "error"'
assert_file_contains doctor-duplicate-state-entry.json '"code":"duplicate_integrity_entry"'

repo_policy_mismatch="${tmp_root}/policy-mismatch"
prepare_manifest_repo "${repo_policy_mismatch}" policy_mismatch
with_manifest .rdl/sessions/policy_mismatch/integrity.json state-policy-human
assert_fails doctor-policy-mismatch.json "${RDL}" doctor
assert_file_contains doctor-policy-mismatch.json '"status": "error"'
assert_file_contains doctor-policy-mismatch.json '"code":"integrity_policy_mismatch"'

repo_unknown_path="${tmp_root}/unknown-path"
prepare_manifest_repo "${repo_unknown_path}" unknown_path
printf 'not an RDL protocol file\n' > .rdl/sessions/unknown_path/project-output.log
with_manifest .rdl/sessions/unknown_path/integrity.json unknown-path
assert_fails doctor-unknown-integrity-path.json "${RDL}" doctor
assert_file_contains doctor-unknown-integrity-path.json '"status": "error"'
assert_file_contains doctor-unknown-integrity-path.json '"code":"unexpected_integrity_entry"'

repo_ledger_rewrite="${tmp_root}/ledger-rewrite"
prepare_manifest_repo "${repo_ledger_rewrite}" ledger_rewrite
sed -i 's/# Decision Ledger/# Rewritten Ledger/' .rdl/sessions/ledger_rewrite/decision-ledger.md
assert_fails doctor-ledger-rewrite.json "${RDL}" doctor
assert_file_contains doctor-ledger-rewrite.json '"status": "error"'
assert_file_contains doctor-ledger-rewrite.json '"code":"integrity_violation_append_only"'

repo_ledger_short="${tmp_root}/ledger-short"
prepare_manifest_repo "${repo_ledger_short}" ledger_short
printf '# Short\n' > .rdl/sessions/ledger_short/decision-ledger.md
assert_fails doctor-ledger-short.json "${RDL}" doctor
assert_file_contains doctor-ledger-short.json '"status": "error"'
assert_file_contains doctor-ledger-short.json '"code":"integrity_violation_append_only"'

repo_prompt_changed="${tmp_root}/prompt-changed"
prepare_manifest_repo "${repo_prompt_changed}" prompt_changed
sed -i 's/^Mode: research$/Mode: build/' .rdl/sessions/prompt_changed/rounds/001/prompt.md
assert_fails doctor-prompt-managed-change.json "${RDL}" doctor
assert_file_contains doctor-prompt-managed-change.json '"status": "error"'
assert_file_contains doctor-prompt-managed-change.json '"code":"integrity_violation_managed_prefix"'

repo_prompt_markers="${tmp_root}/prompt-markers"
prepare_manifest_repo "${repo_prompt_markers}" prompt_markers
sed -i '/rdl:managed/d' .rdl/sessions/prompt_markers/rounds/001/prompt.md
assert_fails doctor-prompt-missing-managed-block.json "${RDL}" doctor
assert_file_contains doctor-prompt-missing-managed-block.json '"status": "error"'
assert_file_contains doctor-prompt-missing-managed-block.json '"code":"missing_managed_block"'

repo_repair_empty_manifest="${tmp_root}/repair-empty-manifest"
prepare_manifest_repo "${repo_repair_empty_manifest}" repair_empty_manifest
with_manifest .rdl/sessions/repair_empty_manifest/integrity.json empty
assert_fails repair-empty-manifest.json "${RDL}" repair
assert_file_contains repair-empty-manifest.json '"status": "error"'
assert_file_contains repair-empty-manifest.json '"action": "repair"'
assert_file_contains repair-empty-manifest.json '"code":"unsafe_integrity_manifest"'
assert_file_contains repair-empty-manifest.json '"file":"integrity.json"'

repo_repair_bad_manifest="${tmp_root}/repair-bad-manifest"
prepare_manifest_repo "${repo_repair_bad_manifest}" repair_bad_manifest
printf '{ broken\n' > .rdl/sessions/repair_bad_manifest/integrity.json
assert_fails repair-bad-manifest.json "${RDL}" repair
assert_file_contains repair-bad-manifest.json '"status": "error"'
assert_file_contains repair-bad-manifest.json '"code":"unsafe_integrity_manifest"'
assert_file_contains repair-bad-manifest.json '"file":"integrity.json"'

repo_repair_policy_mismatch="${tmp_root}/repair-policy-mismatch"
prepare_manifest_repo "${repo_repair_policy_mismatch}" repair_policy_mismatch
with_manifest .rdl/sessions/repair_policy_mismatch/integrity.json state-policy-human
assert_fails repair-policy-mismatch.json "${RDL}" repair
assert_file_contains repair-policy-mismatch.json '"status": "error"'
assert_file_contains repair-policy-mismatch.json '"code":"integrity_policy_mismatch"'
assert_file_contains repair-policy-mismatch.json '"file":"state.json"'

repo_repair_policy_downgrade_changed="${tmp_root}/repair-policy-downgrade-changed"
prepare_manifest_repo "${repo_repair_policy_downgrade_changed}" repair_policy_downgrade_changed
sed -i 's/"phase": "plan"/"phase": "work"/' .rdl/sessions/repair_policy_downgrade_changed/state.json
with_manifest .rdl/sessions/repair_policy_downgrade_changed/integrity.json state-policy-human-current-hash .rdl/sessions/repair_policy_downgrade_changed/state.json
assert_fails repair-policy-downgrade-changed.json "${RDL}" repair
assert_file_contains repair-policy-downgrade-changed.json '"status": "error"'
assert_file_contains repair-policy-downgrade-changed.json '"code":"integrity_policy_mismatch"'
assert_file_contains repair-policy-downgrade-changed.json '"file":"state.json"'
assert_fails repair-policy-downgrade-changed-doctor.json "${RDL}" doctor
assert_file_contains repair-policy-downgrade-changed-doctor.json '"code":"integrity_policy_mismatch"'

repo_repair_missing_state_entry="${tmp_root}/repair-missing-state-entry"
prepare_manifest_repo "${repo_repair_missing_state_entry}" repair_missing_state_entry
with_manifest .rdl/sessions/repair_missing_state_entry/integrity.json remove-state
assert_fails repair-missing-state-entry.json "${RDL}" repair
assert_file_contains repair-missing-state-entry.json '"status": "error"'
assert_file_contains repair-missing-state-entry.json '"code":"missing_integrity_entry"'
assert_file_contains repair-missing-state-entry.json '"file":"state.json"'
assert_fails repair-missing-state-entry-doctor.json "${RDL}" doctor
assert_file_contains repair-missing-state-entry-doctor.json '"code":"missing_integrity_entry"'

repo_repair_missing_state_entry_changed="${tmp_root}/repair-missing-state-entry-changed"
prepare_manifest_repo "${repo_repair_missing_state_entry_changed}" repair_missing_state_entry_changed
with_manifest .rdl/sessions/repair_missing_state_entry_changed/integrity.json remove-state
sed -i 's/"phase": "plan"/"phase": "work"/' .rdl/sessions/repair_missing_state_entry_changed/state.json
assert_fails repair-missing-state-entry-changed.json "${RDL}" repair
assert_file_contains repair-missing-state-entry-changed.json '"status": "error"'
assert_file_contains repair-missing-state-entry-changed.json '"code":"missing_integrity_entry"'
assert_file_contains repair-missing-state-entry-changed.json '"file":"state.json"'
assert_fails repair-missing-state-entry-changed-doctor.json "${RDL}" doctor
assert_file_contains repair-missing-state-entry-changed-doctor.json '"code":"missing_integrity_entry"'

repo_repair_duplicate_state_entry="${tmp_root}/repair-duplicate-state-entry"
prepare_manifest_repo "${repo_repair_duplicate_state_entry}" repair_duplicate_state_entry
with_manifest .rdl/sessions/repair_duplicate_state_entry/integrity.json duplicate-state
assert_fails repair-duplicate-state-entry.json "${RDL}" repair
assert_file_contains repair-duplicate-state-entry.json '"status": "error"'
assert_file_contains repair-duplicate-state-entry.json '"code":"duplicate_integrity_entry"'
assert_file_contains repair-duplicate-state-entry.json '"file":"state.json"'
assert_fails repair-duplicate-state-entry-doctor.json "${RDL}" doctor
assert_file_contains repair-duplicate-state-entry-doctor.json '"code":"duplicate_integrity_entry"'

repo_repair_missing_evidence_entry_changed="${tmp_root}/repair-missing-evidence-entry-changed"
prepare_manifest_repo "${repo_repair_missing_evidence_entry_changed}" repair_missing_evidence_entry_changed
complete_guard_review .rdl/sessions/repair_missing_evidence_entry_changed/rounds/001/review.md
complete_guard_decision .rdl/sessions/repair_missing_evidence_entry_changed/rounds/001/decision.md
complete_guard_research_records .rdl/sessions/repair_missing_evidence_entry_changed/rounds/001
"${RDL}" next > /dev/null
with_manifest .rdl/sessions/repair_missing_evidence_entry_changed/integrity.json remove-evidence
sed -i 's/fixture claim evidence/rewritten fixture claim evidence/' .rdl/sessions/repair_missing_evidence_entry_changed/rounds/001/evidence.md
assert_fails repair-missing-evidence-entry-changed.json "${RDL}" repair
assert_file_contains repair-missing-evidence-entry-changed.json '"status": "error"'
assert_file_contains repair-missing-evidence-entry-changed.json '"code":"missing_integrity_entry"'
assert_file_contains repair-missing-evidence-entry-changed.json '"file":"rounds/001/evidence.md"'

repo_repair_missing_prompt="${tmp_root}/repair-missing-prompt"
prepare_manifest_repo "${repo_repair_missing_prompt}" repair_missing_prompt plan.md
cp .rdl/sessions/repair_missing_prompt/rounds/001/prompt.md original-prompt.md
rm .rdl/sessions/repair_missing_prompt/rounds/001/prompt.md
"${RDL}" repair > repair-missing-prompt.json
assert_file_contains repair-missing-prompt.json '"status": "ok"'
assert_file_contains repair-missing-prompt.json '"next_action": "rounds/001/prompt.md,integrity.json"'
assert_file_contains .rdl/sessions/repair_missing_prompt/rounds/001/prompt.md 'Mode: research'
cmp original-prompt.md .rdl/sessions/repair_missing_prompt/rounds/001/prompt.md || fail "repaired prompt differed from original prompt"
"${RDL}" doctor > repair-missing-prompt-doctor.json
assert_file_contains repair-missing-prompt-doctor.json '"status": "ok"'

repo_repair_missing_prompt_escaped="${tmp_root}/repair-missing-prompt-escaped"
prepare_manifest_repo "${repo_repair_missing_prompt_escaped}" repair_missing_prompt_escaped 'plan"a.md'
cp .rdl/sessions/repair_missing_prompt_escaped/rounds/001/prompt.md original-prompt.md
rm .rdl/sessions/repair_missing_prompt_escaped/rounds/001/prompt.md
"${RDL}" repair > repair-missing-prompt-escaped.json
assert_file_contains repair-missing-prompt-escaped.json '"status": "ok"'
assert_file_contains repair-missing-prompt-escaped.json '"next_action": "rounds/001/prompt.md,integrity.json"'
cmp original-prompt.md .rdl/sessions/repair_missing_prompt_escaped/rounds/001/prompt.md || fail "escaped repaired prompt differed from original prompt"
"${RDL}" doctor > repair-missing-prompt-escaped-doctor.json
assert_file_contains repair-missing-prompt-escaped-doctor.json '"status": "ok"'

repo_start_prompt_control="${tmp_root}/start-prompt-control"
prepare_manifest_repo "${repo_start_prompt_control}" start_prompt_control $'plan\tname.md'
"${RDL}" doctor > start-prompt-control-doctor.json
assert_file_contains start-prompt-control-doctor.json '"status": "ok"'

repo_start_prompt_full_control="${tmp_root}/start-prompt-full-control"
prepare_manifest_repo "${repo_start_prompt_full_control}" start_prompt_full_control $'plan\001name.md'
"${RDL}" doctor > start-prompt-full-control-doctor.json
assert_file_contains start-prompt-full-control-doctor.json '"status": "ok"'

repo_repair_legacy_missing_prompt="${tmp_root}/repair-legacy-missing-prompt"
prepare_manifest_repo "${repo_repair_legacy_missing_prompt}" repair_legacy_missing_prompt
rm .rdl/sessions/repair_legacy_missing_prompt/rounds/001/prompt.md
python3 - .rdl/sessions/repair_legacy_missing_prompt/state.json <<'PY'
import json
import sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)
data.pop("prompt_objective", None)
with open(path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
python3 - .rdl/sessions/repair_legacy_missing_prompt/integrity.json .rdl/sessions/repair_legacy_missing_prompt/state.json <<'PY'
import hashlib
import json
import sys
manifest, state = sys.argv[1], sys.argv[2]
with open(state, "rb") as fh:
    digest = hashlib.sha256(fh.read()).hexdigest()
with open(manifest, "r", encoding="utf-8") as fh:
    data = json.load(fh)
for entry in data["entries"]:
    if entry.get("path") == "state.json":
        entry["sha256"] = digest
with open(manifest, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
assert_fails repair-legacy-missing-prompt.json "${RDL}" repair
assert_file_contains repair-legacy-missing-prompt.json '"status": "blocked"'
assert_file_contains repair-legacy-missing-prompt.json '"code":"missing_prompt_metadata"'
assert_file_contains repair-legacy-missing-prompt.json '"file":"rounds/001/prompt.md"'

repo_repair_noninitial_prompt="${tmp_root}/repair-noninitial-prompt"
prepare_manifest_repo "${repo_repair_noninitial_prompt}" repair_noninitial_prompt
complete_guard_review .rdl/sessions/repair_noninitial_prompt/rounds/001/review.md
complete_guard_decision .rdl/sessions/repair_noninitial_prompt/rounds/001/decision.md
complete_guard_research_records .rdl/sessions/repair_noninitial_prompt/rounds/001
"${RDL}" next > /dev/null
rm .rdl/sessions/repair_noninitial_prompt/rounds/002/prompt.md
assert_fails repair-noninitial-prompt.json "${RDL}" repair
assert_file_contains repair-noninitial-prompt.json '"status": "blocked"'
assert_file_contains repair-noninitial-prompt.json '"code":"unsafe_missing_prompt"'
assert_file_contains repair-noninitial-prompt.json '"file":"rounds/002/prompt.md"'

repo_repair_prior_prompt="${tmp_root}/repair-prior-prompt"
prepare_manifest_repo "${repo_repair_prior_prompt}" repair_prior_prompt
complete_guard_review .rdl/sessions/repair_prior_prompt/rounds/001/review.md
complete_guard_decision .rdl/sessions/repair_prior_prompt/rounds/001/decision.md
complete_guard_research_records .rdl/sessions/repair_prior_prompt/rounds/001
"${RDL}" next > /dev/null
rm .rdl/sessions/repair_prior_prompt/rounds/001/prompt.md
assert_fails repair-prior-prompt.json "${RDL}" repair
assert_file_contains repair-prior-prompt.json '"status": "error"'
assert_file_contains repair-prior-prompt.json '"code":"unsafe_missing_protocol_file"'
assert_file_contains repair-prior-prompt.json '"file":"rounds/001/prompt.md"'
assert_fails repair-prior-prompt-doctor.json "${RDL}" doctor
assert_file_contains repair-prior-prompt-doctor.json '"code":"missing_integrity_file"'
assert_file_contains repair-prior-prompt-doctor.json '"file":"rounds/001/prompt.md"'

repo_repair_prompt_changed="${tmp_root}/repair-prompt-changed"
prepare_manifest_repo "${repo_repair_prompt_changed}" repair_prompt_changed
sed -i 's/^Mode: research$/Mode: build/' .rdl/sessions/repair_prompt_changed/rounds/001/prompt.md
assert_fails repair-prompt-changed.json "${RDL}" repair
assert_file_contains repair-prompt-changed.json '"status": "error"'
assert_file_contains repair-prompt-changed.json '"code":"unsafe_managed_prefix_change"'
assert_file_contains repair-prompt-changed.json '"file":"rounds/001/prompt.md"'

repo_repair_prompt_markers="${tmp_root}/repair-prompt-markers"
prepare_manifest_repo "${repo_repair_prompt_markers}" repair_prompt_markers
sed -i '/rdl:managed/d' .rdl/sessions/repair_prompt_markers/rounds/001/prompt.md
assert_fails repair-prompt-markers.json "${RDL}" repair
assert_file_contains repair-prompt-markers.json '"status": "error"'
assert_file_contains repair-prompt-markers.json '"code":"unsafe_managed_prefix_change"'
assert_file_contains repair-prompt-markers.json '"file":"rounds/001/prompt.md"'

assert_repair_blocks_after_manifest_break "${tmp_root}/repair-empty-changed-state" repair_empty_changed_state empty state.json unsafe_integrity_manifest
assert_repair_blocks_after_manifest_break "${tmp_root}/repair-bad-changed-mission" repair_bad_changed_mission bad mission.md unsafe_integrity_manifest
assert_repair_blocks_after_manifest_break "${tmp_root}/repair-empty-changed-evidence" repair_empty_changed_evidence empty rounds/001/evidence.md unsafe_integrity_manifest
assert_repair_blocks_after_manifest_break "${tmp_root}/repair-bad-changed-decision" repair_bad_changed_decision bad rounds/001/decision.md unsafe_integrity_manifest
assert_repair_blocks_after_manifest_break "${tmp_root}/repair-empty-changed-review" repair_empty_changed_review empty rounds/001/review.md unsafe_integrity_manifest
assert_repair_blocks_after_manifest_break "${tmp_root}/repair-bad-changed-final-report" repair_bad_changed_final_report bad final-report.md unsafe_integrity_manifest

repo_repair_missing_mission="${tmp_root}/repair-missing-mission"
prepare_manifest_repo "${repo_repair_missing_mission}" repair_missing_mission
rm .rdl/sessions/repair_missing_mission/mission.md
assert_fails repair-missing-mission.json "${RDL}" repair
assert_file_contains repair-missing-mission.json '"status": "blocked"'
assert_file_contains repair-missing-mission.json '"code":"unsafe_missing_protocol_file"'
assert_file_contains repair-missing-mission.json '"file":"mission.md"'

assert_repair_blocks_missing_protocol_file "${tmp_root}/repair-missing-factors" repair_missing_factors factors.md
assert_repair_blocks_missing_protocol_file "${tmp_root}/repair-missing-artifact-manifest" repair_missing_artifact_manifest artifact-manifest.json
assert_repair_blocks_missing_protocol_file "${tmp_root}/repair-missing-decision-ledger" repair_missing_decision_ledger decision-ledger.md
assert_repair_blocks_missing_protocol_file "${tmp_root}/repair-missing-progress" repair_missing_progress progress.md

repo_repair_missing_round="${tmp_root}/repair-missing-round"
prepare_manifest_repo "${repo_repair_missing_round}" repair_missing_round
rm -rf .rdl/sessions/repair_missing_round/rounds/001
assert_fails repair-missing-round.json "${RDL}" repair
assert_file_contains repair-missing-round.json '"status": "blocked"'
assert_file_contains repair-missing-round.json '"code":"unsafe_missing_round_dir"'
assert_file_contains repair-missing-round.json '"file":"rounds/001"'

repo_repair_ledger_rewrite="${tmp_root}/repair-ledger-rewrite"
prepare_manifest_repo "${repo_repair_ledger_rewrite}" repair_ledger_rewrite
sed -i 's/# Decision Ledger/# Rewritten Ledger/' .rdl/sessions/repair_ledger_rewrite/decision-ledger.md
assert_fails repair-ledger-rewrite.json "${RDL}" repair
assert_file_contains repair-ledger-rewrite.json '"status": "error"'
assert_file_contains repair-ledger-rewrite.json '"code":"unsafe_append_only_change"'
assert_file_contains repair-ledger-rewrite.json '"file":"decision-ledger.md"'

repo_repair_changed_evidence="${tmp_root}/repair-changed-evidence"
prepare_manifest_repo "${repo_repair_changed_evidence}" repair_changed_evidence
complete_guard_review .rdl/sessions/repair_changed_evidence/rounds/001/review.md
complete_guard_decision .rdl/sessions/repair_changed_evidence/rounds/001/decision.md
complete_guard_research_records .rdl/sessions/repair_changed_evidence/rounds/001
"${RDL}" next > /dev/null
sed -i 's/fixture claim evidence/rewritten fixture claim evidence/' .rdl/sessions/repair_changed_evidence/rounds/001/evidence.md
assert_fails repair-changed-evidence.json "${RDL}" repair
assert_file_contains repair-changed-evidence.json '"status": "error"'
assert_file_contains repair-changed-evidence.json '"code":"unsafe_human_owned_change"'
assert_file_contains repair-changed-evidence.json '"file":"rounds/001/evidence.md"'

repo_repair_changed_decision="${tmp_root}/repair-changed-decision"
prepare_manifest_repo "${repo_repair_changed_decision}" repair_changed_decision
complete_guard_review .rdl/sessions/repair_changed_decision/rounds/001/review.md
complete_guard_decision .rdl/sessions/repair_changed_decision/rounds/001/decision.md
complete_guard_research_records .rdl/sessions/repair_changed_decision/rounds/001
"${RDL}" next > /dev/null
sed -i 's/Decision: continue/Decision: pivot/' .rdl/sessions/repair_changed_decision/rounds/001/decision.md
assert_fails repair-changed-decision.json "${RDL}" repair
assert_file_contains repair-changed-decision.json '"status": "error"'
assert_file_contains repair-changed-decision.json '"code":"unsafe_human_owned_change"'
assert_file_contains repair-changed-decision.json '"file":"rounds/001/decision.md"'

repo_repair_unknown_path="${tmp_root}/repair-unknown-path"
prepare_manifest_repo "${repo_repair_unknown_path}" repair_unknown_path
printf 'not an RDL protocol file\n' > .rdl/sessions/repair_unknown_path/project-output.log
with_manifest .rdl/sessions/repair_unknown_path/integrity.json unknown-path
assert_fails repair-unknown-path.json "${RDL}" repair
assert_file_contains repair-unknown-path.json '"status": "error"'
assert_file_contains repair-unknown-path.json '"code":"unsafe_integrity_entry"'
assert_file_contains repair-unknown-path.json '"file":"project-output.log"'

repo_repair_traversal_path="${tmp_root}/repair-traversal-path"
prepare_manifest_repo "${repo_repair_traversal_path}" repair_traversal_path
mkdir -p .rdl/outside
printf 'outside evidence\n' > .rdl/outside/evidence.md
with_manifest .rdl/sessions/repair_traversal_path/integrity.json traversal-path .rdl/outside/evidence.md
assert_fails repair-traversal-path.json "${RDL}" repair
assert_file_contains repair-traversal-path.json '"status": "error"'
assert_file_contains repair-traversal-path.json '"code":"unsafe_integrity_entry"'
assert_file_contains repair-traversal-path.json '"file":"rounds/001/../../../../outside/evidence.md"'

repo_guard_none="${tmp_root}/guard-none"
mkdir -p "${repo_guard_none}"
cd "${repo_guard_none}"
"${RDL}" guard-stop > guard-none.json
assert_file_contains guard-none.json '"status": "ok"'
assert_file_contains guard-none.json '"action": "guard-stop"'
assert_file_contains guard-none.json '"next_action": "allow"'
[[ ! -d .rdl ]] || fail "guard-stop no-session created RDL state"

repo_guard_fresh="${tmp_root}/guard-fresh"
prepare_manifest_repo "${repo_guard_fresh}" guard_fresh
assert_fails guard-fresh.json "${RDL}" guard-stop
assert_file_contains guard-fresh.json '"status": "blocked"'
assert_file_contains guard-fresh.json '"next_action": "block"'
assert_file_contains guard-fresh.json '"code":"missing_review"'
assert_file_contains guard-fresh.json '"code":"missing_decision"'

repo_guard_ok="${tmp_root}/guard-ok"
prepare_manifest_repo "${repo_guard_ok}" guard_ok
complete_guard_review .rdl/sessions/guard_ok/rounds/001/review.md
complete_guard_decision .rdl/sessions/guard_ok/rounds/001/decision.md
complete_guard_research_records .rdl/sessions/guard_ok/rounds/001
"${RDL}" doctor > guard-ok-doctor-before.json
assert_file_contains guard-ok-doctor-before.json '"status": "ok"'
"${RDL}" guard-stop --guard-session-id guard_ok --guard-command-id g1 > guard-ok.json
assert_file_contains guard-ok.json '"status": "ok"'
assert_file_contains guard-ok.json '"next_action": "allow"'
assert_file_contains .rdl/sessions/guard_ok/state.json '"last_guard_command_id": "g1"'
"${RDL}" guard-stop --guard-session-id guard_ok --guard-command-id g1 > guard-duplicate.json
assert_file_contains guard-duplicate.json '"status": "ok"'
assert_file_contains guard-duplicate.json '"next_action": "allow"'
[[ "$(grep -c '"last_guard_command_id": "g1"' .rdl/sessions/guard_ok/state.json)" -eq 1 ]] || fail "duplicate guard id duplicated state field"
"${RDL}" doctor > guard-post-doctor.json
assert_file_contains guard-post-doctor.json '"status": "ok"'

repo_guard_command_only="${tmp_root}/guard-command-only"
prepare_manifest_repo "${repo_guard_command_only}" guard_command_only
complete_guard_review .rdl/sessions/guard_command_only/rounds/001/review.md
complete_guard_decision .rdl/sessions/guard_command_only/rounds/001/decision.md
complete_guard_research_records .rdl/sessions/guard_command_only/rounds/001
"${RDL}" guard-stop --guard-command-id command-only-1 > guard-command-only.json
assert_file_contains guard-command-only.json '"status": "ok"'
assert_file_contains guard-command-only.json '"next_action": "allow"'
assert_file_contains .rdl/sessions/guard_command_only/state.json '"last_guard_command_id": "command-only-1"'
assert_file_contains .rdl/sessions/guard_command_only/state.json '"guard_session_id": null'

repo_guard_session_only="${tmp_root}/guard-session-only"
prepare_manifest_repo "${repo_guard_session_only}" guard_session_only
complete_guard_review .rdl/sessions/guard_session_only/rounds/001/review.md
complete_guard_decision .rdl/sessions/guard_session_only/rounds/001/decision.md
complete_guard_research_records .rdl/sessions/guard_session_only/rounds/001
"${RDL}" guard-stop --guard-session-id guard_session_only > guard-session-only.json
assert_file_contains guard-session-only.json '"status": "ok"'
assert_file_contains guard-session-only.json '"next_action": "allow"'
assert_file_contains .rdl/sessions/guard_session_only/state.json '"guard_session_id": "guard_session_only"'
assert_file_contains .rdl/sessions/guard_session_only/state.json '"last_guard_command_id": null'
"${RDL}" doctor > guard-session-only-doctor.json
assert_file_contains guard-session-only-doctor.json '"status": "ok"'

repo_guard_build_missing="${tmp_root}/guard-build-missing-verification"
mkdir -p "${repo_guard_build_missing}"
cat > "${repo_guard_build_missing}/mission.md" <<'MISSION'
# Build Mission
MISSION
cd "${repo_guard_build_missing}"
"${RDL}" start build mission.md --session-id guard_build_missing > /dev/null
complete_guard_review .rdl/sessions/guard_build_missing/rounds/001/review.md
complete_guard_build_decision .rdl/sessions/guard_build_missing/rounds/001/decision.md
complete_guard_build_records .rdl/sessions/guard_build_missing/rounds/001 no
assert_fails guard-build-missing.json "${RDL}" guard-stop
assert_file_contains guard-build-missing.json '"status": "blocked"'
assert_file_contains guard-build-missing.json '"code":"missing_verification_evidence"'

repo_guard_build_ok="${tmp_root}/guard-build-ok"
mkdir -p "${repo_guard_build_ok}"
cat > "${repo_guard_build_ok}/mission.md" <<'MISSION'
# Build Mission
MISSION
cd "${repo_guard_build_ok}"
"${RDL}" start build mission.md --session-id guard_build_ok > /dev/null
complete_guard_review .rdl/sessions/guard_build_ok/rounds/001/review.md
complete_guard_build_decision .rdl/sessions/guard_build_ok/rounds/001/decision.md
complete_guard_build_records .rdl/sessions/guard_build_ok/rounds/001 yes
"${RDL}" guard-stop > guard-build-ok.json
assert_file_contains guard-build-ok.json '"status": "ok"'
assert_file_contains guard-build-ok.json '"next_action": "allow"'

repo_guard_close_missing_report="${tmp_root}/guard-close-missing-report"
prepare_guard_close_repo "${repo_guard_close_missing_report}" guard_close_missing_report
assert_fails guard-close-missing-report.json "${RDL}" guard-stop
assert_file_contains guard-close-missing-report.json '"status": "blocked"'
assert_file_contains guard-close-missing-report.json '"code":"missing_final_report"'

repo_guard_close_missing_evidence="${tmp_root}/guard-close-missing-evidence"
prepare_guard_close_repo "${repo_guard_close_missing_evidence}" guard_close_missing_evidence
complete_guard_final_report .rdl/sessions/guard_close_missing_evidence/final-report.md
sed -i '/^## Missing Evidence$/,/^## Known Confounders$/ { /^## Known Confounders$/!d; }' .rdl/sessions/guard_close_missing_evidence/rounds/001/evidence.md
assert_fails guard-close-missing-evidence.json "${RDL}" guard-stop
assert_file_contains guard-close-missing-evidence.json '"status": "blocked"'
assert_file_contains guard-close-missing-evidence.json '"code":"missing_evidence_discipline"'

repo_guard_close_open="${tmp_root}/guard-close-open-question"
prepare_guard_close_repo "${repo_guard_close_open}" guard_close_open
complete_guard_final_report .rdl/sessions/guard_close_open/final-report.md
write_guard_blocking_question_progress .rdl/sessions/guard_close_open/progress.md
assert_fails guard-close-open-question.json "${RDL}" guard-stop
assert_file_contains guard-close-open-question.json '"status": "blocked"'
assert_file_contains guard-close-open-question.json '"code":"unresolved_blocking_open_questions"'

repo_guard_close_deferred="${tmp_root}/guard-close-deferred"
prepare_guard_close_repo "${repo_guard_close_deferred}" guard_close_deferred
complete_guard_final_report .rdl/sessions/guard_close_deferred/final-report.md
write_guard_bad_deferred_progress .rdl/sessions/guard_close_deferred/progress.md
assert_fails guard-close-deferred.json "${RDL}" guard-stop
assert_file_contains guard-close-deferred.json '"status": "blocked"'
assert_file_contains guard-close-deferred.json '"code":"incomplete_deferred_items"'

repo_guard_close_citation="${tmp_root}/guard-close-citation"
prepare_guard_close_repo "${repo_guard_close_citation}" guard_close_citation
complete_guard_final_report .rdl/sessions/guard_close_citation/final-report.md
cp "${ROOT_DIR}/local/research-dev-loop/templates/artifact-manifest.json" .rdl/sessions/guard_close_citation/artifact-manifest.json
assert_fails guard-close-citation.json "${RDL}" guard-stop
assert_file_contains guard-close-citation.json '"status": "blocked"'
assert_file_contains guard-close-citation.json '"code":"missing_artifact_citation"'

repo_guard_close_ok="${tmp_root}/guard-close-ok"
prepare_guard_close_repo "${repo_guard_close_ok}" guard_close_ok
complete_guard_final_report .rdl/sessions/guard_close_ok/final-report.md
"${RDL}" guard-stop > guard-close-ok.json
assert_file_contains guard-close-ok.json '"status": "ok"'
assert_file_contains guard-close-ok.json '"next_action": "allow"'

repo_guard_mismatch="${tmp_root}/guard-mismatch"
prepare_manifest_repo "${repo_guard_mismatch}" guard_mismatch
"${RDL}" guard-stop --guard-session-id other --guard-command-id mismatch1 > guard-mismatch.json
assert_file_contains guard-mismatch.json '"status": "ok"'
assert_file_contains guard-mismatch.json '"next_action": "allow"'
assert_file_contains .rdl/sessions/guard_mismatch/state.json '"last_guard_command_id": null'

repo_guard_block="${tmp_root}/guard-block"
prepare_manifest_repo "${repo_guard_block}" guard_block
rm .rdl/sessions/guard_block/progress.md
assert_fails guard-block.json "${RDL}" guard-stop
assert_file_contains guard-block.json '"status": "blocked"'
assert_file_contains guard-block.json '"next_action": "block"'
assert_file_contains guard-block.json '"code":"missing_required_file"'

repo_guard_corrupt="${tmp_root}/guard-corrupt"
mkdir -p "${repo_guard_corrupt}/.rdl/sessions/bad"
printf '{ broken\n' > "${repo_guard_corrupt}/.rdl/sessions/bad/state.json"
cd "${repo_guard_corrupt}"
assert_fails guard-corrupt.json "${RDL}" guard-stop
assert_file_contains guard-corrupt.json '"status": "error"'
assert_file_contains guard-corrupt.json '"next_action": "block"'
assert_file_contains guard-corrupt.json '"code":"invalid_state_json"'

cd "${repo}"
rm .rdl/sessions/r1/progress.md
assert_fails doctor-missing.json "${RDL}" doctor
assert_file_contains doctor-missing.json '"status": "blocked"'
assert_file_contains doctor-missing.json '"code":"missing_required_file"'
assert_file_contains doctor-missing.json '"file":"progress.md"'

cp "${ROOT_DIR}/local/research-dev-loop/templates/progress.md" .rdl/sessions/r1/progress.md
printf '{ broken\n' > .rdl/sessions/r1/artifact-manifest.json
assert_fails doctor-bad-manifest.json "${RDL}" doctor
assert_file_contains doctor-bad-manifest.json '"status": "error"'
assert_file_contains doctor-bad-manifest.json '"code":"invalid_artifact_manifest_json"'

cat > .rdl/sessions/r1/artifact-manifest.json <<'JSON'
{
  "artifacts": [
    {
      "id": "A1",
      "kind": "benchmark"
    }
  ]
}
JSON
assert_fails doctor-invalid-artifact.json "${RDL}" doctor
assert_file_contains doctor-invalid-artifact.json '"status": "blocked"'
assert_file_contains doctor-invalid-artifact.json '"code":"invalid_artifact_entry"'

cp "${ROOT_DIR}/local/research-dev-loop/templates/artifact-manifest.json" .rdl/sessions/r1/artifact-manifest.json
printf '{ broken\n' > .rdl/sessions/r1/state.json
assert_fails status-corrupt.json "${RDL}" status
assert_file_contains status-corrupt.json '"status": "error"'
assert_file_contains status-corrupt.json '"code":"invalid_state_json"'

repo2="${tmp_root}/repo2"
mkdir -p "${repo2}/.rdl/sessions/bad"
printf '{ broken\n' > "${repo2}/.rdl/sessions/bad/state.json"
cd "${repo2}"
assert_fails doctor-corrupt.json "${RDL}" doctor
assert_file_contains doctor-corrupt.json '"status": "error"'
assert_file_contains doctor-corrupt.json '"code":"invalid_state_json"'

repo3="${tmp_root}/repo3"
mkdir -p "${repo3}/.rdl/sessions/bad"
cat > "${repo3}/.rdl/sessions/bad/state.json" <<'JSON'
{
  "schema_version": 2,
  "session_id": "bad",
  "mode": "research",
  "phase": "plan",
  "round": 1,
  "status": "closed-positive",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cd "${repo3}"
assert_fails doctor-unsupported.json "${RDL}" doctor
assert_file_contains doctor-unsupported.json '"status": "error"'
assert_file_contains doctor-unsupported.json '"code":"unsupported_schema"'

repo4="${tmp_root}/repo4"
mkdir -p "${repo4}/.rdl/sessions/bad"
cat > "${repo4}/.rdl/sessions/bad/state.json" <<'JSON'
{
  "schema_version": 1,
  "session_id": "bad",
  "mode": "research",
  "phase": "plan",
  "round": 1,
  "status": "nonsense",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cd "${repo4}"
assert_fails doctor-invalid-status.json "${RDL}" doctor
assert_file_contains doctor-invalid-status.json '"status": "error"'
assert_file_contains doctor-invalid-status.json '"code":"invalid_status"'

repo5="${tmp_root}/repo5"
mkdir -p "${repo5}/.rdl/sessions/done"
cat > "${repo5}/.rdl/sessions/done/state.json" <<'JSON'
{
  "schema_version": 1,
  "session_id": "done",
  "mode": "research",
  "phase": "complete",
  "round": 1,
  "status": "closed-positive",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cd "${repo5}"
"${RDL}" status > status-closed.json
assert_file_contains status-closed.json '"status": "ok"'
assert_file_contains status-closed.json '"next_action": "rdl start research <mission.md>"'

repo6="${tmp_root}/repo6"
mkdir -p "${repo6}/.rdl/sessions/bad"
cat > "${repo6}/mission.md" <<'MISSION'
# Mission
MISSION
cat > "${repo6}/.rdl/sessions/bad/state.json" <<'JSON'
{
  "schema_version": 2,
  "session_id": "bad",
  "mode": "research",
  "phase": "plan",
  "round": 1,
  "status": "closed-positive",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cd "${repo6}"
assert_fails start-unsupported.json "${RDL}" start research mission.md --session-id new
assert_file_contains start-unsupported.json '"status": "error"'
assert_file_contains start-unsupported.json '"code":"unsupported_schema"'
[[ ! -e .rdl/sessions/new ]] || fail "start created a new session despite unsupported existing schema"

repo7="${tmp_root}/repo7"
mkdir -p "${repo7}/.rdl/sessions/bad"
cat > "${repo7}/mission.md" <<'MISSION'
# Mission
MISSION
cat > "${repo7}/.rdl/sessions/bad/state.json" <<'JSON'
{
  "schema_version": 1,
  "session_id": "bad",
  "mode": "research",
  "phase": "plan",
  "round": 1,
  "status": "nonsense",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cd "${repo7}"
assert_fails start-invalid-status.json "${RDL}" start research mission.md --session-id new
assert_file_contains start-invalid-status.json '"status": "error"'
assert_file_contains start-invalid-status.json '"code":"invalid_status"'
[[ ! -e .rdl/sessions/new ]] || fail "start created a new session despite invalid existing status"

repo8="${tmp_root}/repo8"
mkdir -p "${repo8}/.rdl/sessions/done" "${repo8}/.rdl/sessions/old"
cat > "${repo8}/mission.md" <<'MISSION'
# Mission
MISSION
cat > "${repo8}/.rdl/sessions/done/state.json" <<'JSON'
{
  "schema_version": 1,
  "session_id": "done",
  "mode": "research",
  "phase": "complete",
  "round": 1,
  "status": "closed-positive",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cat > "${repo8}/.rdl/sessions/old/state.json" <<'JSON'
{
  "schema_version": 1,
  "session_id": "old",
  "mode": "build",
  "phase": "complete",
  "round": 1,
  "status": "abandoned",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cd "${repo8}"
"${RDL}" start research mission.md --session-id new > start-after-closed.json
assert_file_contains start-after-closed.json '"status": "ok"'
assert_file_contains start-after-closed.json '"session_id": "new"'
[[ -d .rdl/sessions/new ]] || fail "start did not create a new session after valid closed sessions"

repo9="${tmp_root}/repo9"
mkdir -p "${repo9}/.rdl/sessions/bad"
cat > "${repo9}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo9}"
assert_fails start-missing-state.json "${RDL}" start research mission.md --session-id new
assert_file_contains start-missing-state.json '"status": "error"'
assert_file_contains start-missing-state.json '"code":"missing_state"'
[[ ! -e .rdl/sessions/new ]] || fail "start created a new session despite missing existing state"

echo "round1 tests ok"

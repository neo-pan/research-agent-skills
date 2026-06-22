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

complete_review() {
  local file="$1"
  cat > "${file}" <<'REVIEW'
# Review

Reviewer: fixture
Review Mode: manual
Review Scope: current round
Artifacts Reviewed: prompt, evidence, decision
Verdict: PASS
Decision Reviewed: close decision
Evidence Reviewed: fixture evidence
Blocking Evidence Gaps: none
Implementation Findings: none
Evaluation Integrity Findings: acceptable
Overclaim Risks: bounded
Readiness Level: ready
Recommended Decision: close

REVIEW
}

complete_decision() {
  local file="$1"
  local decision="$2"
  local closes="$3"
  cat > "${file}" <<DECISION
# Decision

Decision: ${decision}
Closes: ${closes}
Evidence: E1 fixture evidence
Uncertainty: bounded
What this rules out: unsupported alternatives
What remains unknown: later work
Recommended next loop: none
Next smallest step: close the session

DECISION
}

complete_manifest() {
  local file="$1"
  local artifact_id="${2:-E1}"
  cat > "${file}" <<MANIFEST
{
  "artifacts": [
    {
      "id": "${artifact_id}",
      "kind": "log",
      "path": "artifacts/check.log"
    }
  ]
}
MANIFEST
}

complete_research_records() {
  local round_dir="$1"
  cat > "${round_dir}/evidence.md" <<'EVIDENCE'
# Evidence

## Claim Under Review

Fixture claim.

## Evidence Artifacts

| ID | Kind | Path or URL | Supports | Notes |
|---|---|---|---|---|
| E1 | log | artifacts/check.log | claim | fixture evidence cited |

## Controls and Baselines

Fixture baseline noted.

## Evaluation Integrity

Manual fixture integrity reviewed.

## Missing Evidence

No blocking missing evidence for this fixture.

## Known Confounders

No known blocking confounders.

## Evidence Budget

One local fixture check.

## Reproducibility

Fixture script is deterministic.

## Strength of Support

Moderate
EVIDENCE
  cat > "${round_dir}/interpretation.md" <<'INTERPRETATION'
# Interpretation

Interpretation: fixture evidence supports closing the claim.
INTERPRETATION
}

append_repeated_negative_evidence() {
  local evidence_file="$1"
  cat >> "${evidence_file}" <<'EVIDENCE'

## Repeated Negative Evidence

The same negative fixture result repeated after the prior continue decision.
EVIDENCE
}

complete_build_records() {
  local round_dir="$1"
  cat > "${round_dir}/intent.md" <<'INTENT'
# Intent

Intent: close the fixture capability.
INTENT
  cat > "${round_dir}/work.md" <<'WORK'
# Work

Work: fixture capability implemented.
WORK
  cat > "${round_dir}/evidence.md" <<'EVIDENCE'
# Evidence

## Verification Evidence

| Result |
|---|
| fixture check passed |

## Evaluation Integrity

Manual fixture integrity reviewed.

## Missing Evidence

No blocking missing evidence for this fixture.

## Evidence Budget

One local fixture check.
EVIDENCE
}

complete_final_report() {
  local file="$1"
  local outcome="$2"
  local closed="$3"
  cat > "${file}" <<REPORT
# Final Report

## Outcome

${outcome}

## Claim or Capability Closed

${closed}

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

write_ready_progress() {
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

write_blocking_question_progress() {
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

## Open Questions

| Question | Owner | Blocking? | Resolution |
|---|---|---|---|
| Is release timing known? | fixture | no | Non-blocking follow-up. |
| Is the claim still uncertain? | fixture | yes | - |
PROGRESS
}

write_bad_deferred_progress() {
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

prepare_two_round_repeated_negative_close() {
  local repo="$1"
  local session_id="$2"
  local outcome="${3:-positive}"
  mkdir -p "${repo}"
  cat > "${repo}/mission.md" <<'MISSION'
# Mission

Repeated negative fixture.
MISSION
  cd "${repo}"
  "${RDL}" start research mission.md --session-id "${session_id}" > /dev/null
  "${RDL}" review > /dev/null
  complete_review ".rdl/sessions/${session_id}/rounds/001/review.md"
  "${RDL}" decide continue > /dev/null
  complete_decision ".rdl/sessions/${session_id}/rounds/001/decision.md" continue claim
  complete_research_records ".rdl/sessions/${session_id}/rounds/001"
  complete_manifest ".rdl/sessions/${session_id}/artifact-manifest.json"
  "${RDL}" next > /dev/null
  "${RDL}" review > /dev/null
  complete_review ".rdl/sessions/${session_id}/rounds/002/review.md"
  "${RDL}" decide "close-${outcome}" > /dev/null
  complete_decision ".rdl/sessions/${session_id}/rounds/002/decision.md" "close-${outcome}" claim
  complete_research_records ".rdl/sessions/${session_id}/rounds/002"
  append_repeated_negative_evidence ".rdl/sessions/${session_id}/rounds/002/evidence.md"
  complete_final_report ".rdl/sessions/${session_id}/final-report.md" "${outcome}" "fixture claim"
  write_ready_progress ".rdl/sessions/${session_id}/progress.md"
}

tmp_root="$(mktemp -d)"
trap 'rm -rf "${tmp_root}"' EXIT

for outcome in positive negative inconclusive; do
  repo="${tmp_root}/close-${outcome}"
  mkdir -p "${repo}"
  cat > "${repo}/mission.md" <<'MISSION'
# Mission

Close fixture.
MISSION
  cd "${repo}"
  "${RDL}" start research mission.md --session-id "close_${outcome}" > /dev/null
  "${RDL}" review > /dev/null
  complete_review ".rdl/sessions/close_${outcome}/rounds/001/review.md"
  "${RDL}" decide "close-${outcome}" > /dev/null
  complete_decision ".rdl/sessions/close_${outcome}/rounds/001/decision.md" "close-${outcome}" claim
  complete_research_records ".rdl/sessions/close_${outcome}/rounds/001"
  complete_final_report ".rdl/sessions/close_${outcome}/final-report.md" "${outcome}" "fixture claim"
  complete_manifest ".rdl/sessions/close_${outcome}/artifact-manifest.json"
  write_ready_progress ".rdl/sessions/close_${outcome}/progress.md"
  "${RDL}" close "${outcome}" > "close-${outcome}.json"
  assert_file_contains "close-${outcome}.json" '"status": "ok"'
  assert_file_contains "close-${outcome}.json" '"action": "close"'
  assert_file_contains "close-${outcome}.json" "\"next_action\": \"closed-${outcome}\""
  assert_file_contains ".rdl/sessions/close_${outcome}/state.json" "\"status\": \"closed-${outcome}\""
  assert_file_contains ".rdl/sessions/close_${outcome}/state.json" '"phase": "complete"'
  assert_file_contains ".rdl/sessions/close_${outcome}/decision-ledger.md" '## Session Closed'
done

repo_missing="${tmp_root}/close-missing-report"
mkdir -p "${repo_missing}"
cat > "${repo_missing}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo_missing}"
"${RDL}" start research mission.md --session-id close_missing_report > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/close_missing_report/rounds/001/review.md
"${RDL}" decide close-positive > /dev/null
complete_decision .rdl/sessions/close_missing_report/rounds/001/decision.md close-positive claim
complete_research_records .rdl/sessions/close_missing_report/rounds/001
assert_fails close-missing-report.json "${RDL}" close positive
assert_file_contains close-missing-report.json '"status": "blocked"'
assert_file_contains close-missing-report.json '"code":"missing_final_report"'
assert_file_contains .rdl/sessions/close_missing_report/state.json '"status": "active"'

repo_unchecked="${tmp_root}/close-unchecked"
mkdir -p "${repo_unchecked}"
cat > "${repo_unchecked}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo_unchecked}"
"${RDL}" start research mission.md --session-id close_unchecked > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/close_unchecked/rounds/001/review.md
"${RDL}" decide close-positive > /dev/null
complete_decision .rdl/sessions/close_unchecked/rounds/001/decision.md close-positive claim
complete_research_records .rdl/sessions/close_unchecked/rounds/001
cp "${ROOT_DIR}/local/research-dev-loop/templates/final-report.md" .rdl/sessions/close_unchecked/final-report.md
assert_fails close-unchecked.json "${RDL}" close positive
assert_file_contains close-unchecked.json '"status": "blocked"'
assert_file_contains close-unchecked.json '"code":"missing_final_report_section"'
assert_file_contains close-unchecked.json '"code":"incomplete_close_checklist"'

repo_open="${tmp_root}/close-open-question"
mkdir -p "${repo_open}"
cat > "${repo_open}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo_open}"
"${RDL}" start research mission.md --session-id close_open_question > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/close_open_question/rounds/001/review.md
"${RDL}" decide close-positive > /dev/null
complete_decision .rdl/sessions/close_open_question/rounds/001/decision.md close-positive claim
complete_research_records .rdl/sessions/close_open_question/rounds/001
complete_final_report .rdl/sessions/close_open_question/final-report.md positive "fixture claim"
complete_manifest .rdl/sessions/close_open_question/artifact-manifest.json
write_blocking_question_progress .rdl/sessions/close_open_question/progress.md
assert_fails close-open-question.json "${RDL}" close positive
assert_file_contains close-open-question.json '"status": "blocked"'
assert_file_contains close-open-question.json '"code":"unresolved_blocking_open_questions"'
complete_decision .rdl/sessions/close_open_question/rounds/001/decision.md close-inconclusive claim
assert_fails close-open-question-outcome-mismatch.json "${RDL}" close inconclusive
assert_file_contains close-open-question-outcome-mismatch.json '"status": "blocked"'
assert_file_contains close-open-question-outcome-mismatch.json '"code":"close_outcome_mismatch"'
complete_final_report .rdl/sessions/close_open_question/final-report.md inconclusive "fixture claim"
"${RDL}" close inconclusive > close-open-question-inconclusive.json
assert_file_contains close-open-question-inconclusive.json '"status": "ok"'
assert_file_contains .rdl/sessions/close_open_question/state.json '"status": "closed-inconclusive"'

repo_deferred="${tmp_root}/close-deferred"
mkdir -p "${repo_deferred}"
cat > "${repo_deferred}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo_deferred}"
"${RDL}" start build mission.md --session-id close_deferred > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/close_deferred/rounds/001/review.md
"${RDL}" decide close-negative > /dev/null
complete_decision .rdl/sessions/close_deferred/rounds/001/decision.md close-negative capability
complete_build_records .rdl/sessions/close_deferred/rounds/001
complete_final_report .rdl/sessions/close_deferred/final-report.md negative "fixture capability"
write_bad_deferred_progress .rdl/sessions/close_deferred/progress.md
assert_fails close-deferred.json "${RDL}" close negative
assert_file_contains close-deferred.json '"status": "blocked"'
assert_file_contains close-deferred.json '"code":"incomplete_deferred_items"'

repo_missing_negative="${tmp_root}/close-missing-negative-section"
mkdir -p "${repo_missing_negative}"
cat > "${repo_missing_negative}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo_missing_negative}"
"${RDL}" start research mission.md --session-id close_missing_negative > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/close_missing_negative/rounds/001/review.md
"${RDL}" decide close-positive > /dev/null
complete_decision .rdl/sessions/close_missing_negative/rounds/001/decision.md close-positive claim
complete_research_records .rdl/sessions/close_missing_negative/rounds/001
complete_manifest .rdl/sessions/close_missing_negative/artifact-manifest.json
complete_final_report .rdl/sessions/close_missing_negative/final-report.md positive "fixture claim"
sed -i '/^## Negative, Null, or Inconclusive Results$/,/^## Open Questions$/ { /^## Open Questions$/!d; }' .rdl/sessions/close_missing_negative/final-report.md
write_ready_progress .rdl/sessions/close_missing_negative/progress.md
assert_fails close-missing-negative-section.json "${RDL}" close positive
assert_file_contains close-missing-negative-section.json '"status": "blocked"'
assert_file_contains close-missing-negative-section.json '"code":"missing_final_report_section"'

repo_not_positive="${tmp_root}/close-not-positive"
mkdir -p "${repo_not_positive}"
cat > "${repo_not_positive}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo_not_positive}"
"${RDL}" start research mission.md --session-id close_not_positive > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/close_not_positive/rounds/001/review.md
"${RDL}" decide close-positive > /dev/null
complete_decision .rdl/sessions/close_not_positive/rounds/001/decision.md close-positive claim
complete_research_records .rdl/sessions/close_not_positive/rounds/001
complete_manifest .rdl/sessions/close_not_positive/artifact-manifest.json
complete_final_report .rdl/sessions/close_not_positive/final-report.md "not positive" "fixture claim"
write_ready_progress .rdl/sessions/close_not_positive/progress.md
assert_fails close-not-positive.json "${RDL}" close positive
assert_file_contains close-not-positive.json '"status": "blocked"'
assert_file_contains close-not-positive.json '"code":"close_outcome_mismatch"'

repo_missing_citation="${tmp_root}/close-missing-citation"
mkdir -p "${repo_missing_citation}"
cat > "${repo_missing_citation}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo_missing_citation}"
"${RDL}" start research mission.md --session-id close_missing_citation > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/close_missing_citation/rounds/001/review.md
"${RDL}" decide close-positive > /dev/null
complete_decision .rdl/sessions/close_missing_citation/rounds/001/decision.md close-positive claim
complete_research_records .rdl/sessions/close_missing_citation/rounds/001
complete_final_report .rdl/sessions/close_missing_citation/final-report.md positive "fixture claim"
write_ready_progress .rdl/sessions/close_missing_citation/progress.md
assert_fails close-missing-citation.json "${RDL}" close positive
assert_file_contains close-missing-citation.json '"status": "blocked"'
assert_file_contains close-missing-citation.json '"code":"missing_artifact_citation"'
assert_file_contains close-missing-citation.json 'artifact ID E1'
assert_file_contains .rdl/sessions/close_missing_citation/state.json '"status": "active"'

repo_manifest_citation="${tmp_root}/close-manifest-citation"
mkdir -p "${repo_manifest_citation}"
cat > "${repo_manifest_citation}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo_manifest_citation}"
"${RDL}" start research mission.md --session-id close_manifest_citation > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/close_manifest_citation/rounds/001/review.md
"${RDL}" decide close-positive > /dev/null
complete_decision .rdl/sessions/close_manifest_citation/rounds/001/decision.md close-positive claim
complete_research_records .rdl/sessions/close_manifest_citation/rounds/001
complete_manifest .rdl/sessions/close_manifest_citation/artifact-manifest.json
complete_final_report .rdl/sessions/close_manifest_citation/final-report.md positive "fixture claim"
write_ready_progress .rdl/sessions/close_manifest_citation/progress.md
"${RDL}" close positive > close-manifest-citation.json
assert_file_contains close-manifest-citation.json '"status": "ok"'
assert_file_contains .rdl/sessions/close_manifest_citation/state.json '"status": "closed-positive"'

repo_repeated_block="${tmp_root}/close-repeated-block"
prepare_two_round_repeated_negative_close "${repo_repeated_block}" repeated_block positive
assert_fails close-repeated-block.json "${RDL}" close positive
assert_file_contains close-repeated-block.json '"status": "blocked"'
assert_file_contains close-repeated-block.json '"code":"unacknowledged_repeated_negative_evidence"'
assert_file_contains .rdl/sessions/repeated_block/state.json '"status": "active"'

repo_repeated_decision="${tmp_root}/close-repeated-decision"
prepare_two_round_repeated_negative_close "${repo_repeated_decision}" repeated_decision positive
cat >> .rdl/sessions/repeated_decision/rounds/002/decision.md <<'DECISION'

Repeated negative evidence acknowledged; continue justified by the bounded fixture close rationale.
DECISION
"${RDL}" close positive > close-repeated-decision.json
assert_file_contains close-repeated-decision.json '"status": "ok"'
assert_file_contains .rdl/sessions/repeated_decision/state.json '"status": "closed-positive"'

repo_repeated_progress="${tmp_root}/close-repeated-progress"
prepare_two_round_repeated_negative_close "${repo_repeated_progress}" repeated_progress positive
cat >> .rdl/sessions/repeated_progress/progress.md <<'PROGRESS'

## Repeated Negative Evidence Acknowledgement

Repeated failure acknowledged; close rationale explains why the session can end.
PROGRESS
"${RDL}" close positive > close-repeated-progress.json
assert_file_contains close-repeated-progress.json '"status": "ok"'
assert_file_contains .rdl/sessions/repeated_progress/state.json '"status": "closed-positive"'

repo_no_repeated="${tmp_root}/close-no-repeated-section"
prepare_two_round_repeated_negative_close "${repo_no_repeated}" no_repeated positive
sed -i '/^## Repeated Negative Evidence$/,$d' .rdl/sessions/no_repeated/rounds/002/evidence.md
"${RDL}" close positive > close-no-repeated-section.json
assert_file_contains close-no-repeated-section.json '"status": "ok"'
assert_file_contains .rdl/sessions/no_repeated/state.json '"status": "closed-positive"'

repo_abandon="${tmp_root}/abandon"
mkdir -p "${repo_abandon}"
cat > "${repo_abandon}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo_abandon}"
"${RDL}" start build mission.md --session-id abandon1 > /dev/null
"${RDL}" abandon "operator stopped duplicate effort" > abandon.json
assert_file_contains abandon.json '"status": "ok"'
assert_file_contains abandon.json '"action": "abandon"'
assert_file_contains abandon.json '"next_action": "abandoned"'
assert_file_contains .rdl/sessions/abandon1/state.json '"status": "abandoned"'
assert_file_contains .rdl/sessions/abandon1/state.json '"phase": "complete"'
assert_file_contains .rdl/sessions/abandon1/decision-ledger.md 'Scientific outcome claimed: none'
assert_file_contains .rdl/sessions/abandon1/progress.md 'operator stopped duplicate effort'
assert_fails close-after-abandon.json "${RDL}" close positive
assert_file_contains close-after-abandon.json '"status": "blocked"'
assert_file_contains close-after-abandon.json '"code":"no_active_session"'

repo_no_reason="${tmp_root}/abandon-no-reason"
mkdir -p "${repo_no_reason}"
cat > "${repo_no_reason}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo_no_reason}"
"${RDL}" start research mission.md --session-id abandon_no_reason > /dev/null
assert_fails abandon-no-reason.json "${RDL}" abandon
assert_file_contains abandon-no-reason.json '"status": "error"'
assert_file_contains abandon-no-reason.json '"code":"missing_abandon_reason"'
assert_file_contains .rdl/sessions/abandon_no_reason/state.json '"status": "active"'

echo "round3 tests ok"

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

assert_file_absent() {
  [[ ! -e "$1" ]] || fail "unexpected file exists: $1"
}

complete_review() {
  local file="$1"
  local recommended="${2:-continue}"
  cat > "${file}" <<REVIEW
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
Recommended Decision: ${recommended}

REVIEW
}

complete_decision() {
  local file="$1"
  local decision="$2"
  local closes="$3"
  local next_loop="${4:-none}"
  cat > "${file}" <<DECISION
# Decision

Decision: ${decision}
Closes: ${closes}
Evidence: E1 fixture evidence
Uncertainty: bounded
What this rules out: unsupported alternatives
What remains unknown: later work
Recommended next loop: ${next_loop}
Next smallest step: continue same mode

DECISION
}

complete_manifest() {
  local file="$1"
  cat > "${file}" <<'MANIFEST'
{
  "artifacts": [
    {
      "id": "E1",
      "kind": "log",
      "path": "artifacts/check.log",
      "round": 1,
      "description": "Fixture transition evidence"
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

## Evaluation Integrity

Manual fixture integrity reviewed.

## Missing Evidence

No blocking missing evidence for this fixture.

## Evidence Budget

One local fixture check.
EVIDENCE
  cat > "${round_dir}/interpretation.md" <<'INTERPRETATION'
# Interpretation

Interpretation: fixture evidence supports the transition.
INTERPRETATION
}

complete_final_report() {
  local file="$1"
  local outcome="$2"
  cat > "${file}" <<REPORT
# Final Report

## Outcome

${outcome}

## Claim or Capability Closed

Fixture claim.

## Evidence Cited

E1 fixture evidence.

## Missing Evidence and Confounders

No blocking missing evidence or confounders remain.

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
PROGRESS
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
assert_file_contains review-next.json '"next_action": ".rdl/sessions/transition_next/rounds/002/review.md"'

repo_close="${tmp_root}/close"
start_research_repo "${repo_close}" transition_close
"${RDL}" review > /dev/null
complete_review .rdl/sessions/transition_close/rounds/001/review.md close
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
complete_review .rdl/sessions/transition_guard/rounds/001/review.md close
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

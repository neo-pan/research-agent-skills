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

complete_decision() {
  local file="$1"
  local decision="$2"
  local closes="$3"
  local next_loop="$4"
  cat > "${file}" <<DECISION
# Decision

Decision: ${decision}
Closes: ${closes}
Evidence: fixture evidence
Uncertainty: bounded
What this rules out: unsupported alternatives
What remains unknown: later work
Recommended next loop: ${next_loop}
Next smallest step: continue same mode

DECISION
}

add_research_round_records() {
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

add_build_round_records() {
  local round_dir="$1"
  cat > "${round_dir}/intent.md" <<'INTENT'
# Intent

Intent: build the fixture capability.
INTENT
  cat > "${round_dir}/work.md" <<'WORK'
# Work

Work completed: fixture implementation change.
WORK
  cat > "${round_dir}/evidence.md" <<'EVIDENCE'
# Evidence

Verification evidence: fixture capability check passed.
EVIDENCE
}

tmp_root="$(mktemp -d)"
trap 'rm -rf "${tmp_root}"' EXIT

repo="${tmp_root}/research"
mkdir -p "${repo}"
cat > "${repo}/mission.md" <<'MISSION'
# Mission

Round 2 research fixture.
MISSION
cd "${repo}"

"${RDL}" start research mission.md --session-id research1 > start.json
"${RDL}" review > review-created.json
assert_file_contains review-created.json '"status": "ok"'
assert_file_contains review-created.json '"next_action": ".rdl/sessions/research1/rounds/001/review.md"'
[[ -f .rdl/sessions/research1/rounds/001/review.md ]] || fail "review did not create review.md"

assert_fails next-missing-decision.json "${RDL}" next
assert_file_contains next-missing-decision.json '"status": "blocked"'
assert_file_contains next-missing-decision.json '"code":"missing_review_field"'
assert_file_contains next-missing-decision.json '"code":"missing_decision"'

complete_review .rdl/sessions/research1/rounds/001/review.md
assert_fails decide-invalid-type.json "${RDL}" decide unsupported
assert_file_contains decide-invalid-type.json '"status": "error"'
assert_file_contains decide-invalid-type.json '"code":"invalid_decision_type"'

"${RDL}" decide continue > decide-created.json
assert_file_contains decide-created.json '"status": "ok"'
assert_file_contains .rdl/sessions/research1/rounds/001/decision.md '^Decision: continue$'
assert_file_contains .rdl/sessions/research1/rounds/001/decision.md '^Closes: claim$'

complete_decision .rdl/sessions/research1/rounds/001/decision.md continue claim build
assert_fails decide-mismatch.json "${RDL}" decide accept
assert_file_contains decide-mismatch.json '"status": "blocked"'
assert_file_contains decide-mismatch.json '"code":"decision_type_mismatch"'
add_research_round_records .rdl/sessions/research1/rounds/001
"${RDL}" next > next-research.json
assert_file_contains next-research.json '"status": "ok"'
assert_file_contains next-research.json '"round": 2'
assert_file_contains next-research.json '"mode": "research"'
assert_file_contains .rdl/sessions/research1/state.json '"mode": "research"'
assert_file_contains .rdl/sessions/research1/state.json '"round": 2'
assert_file_contains .rdl/sessions/research1/rounds/002/prompt.md 'Mode: research'
assert_file_contains .rdl/sessions/research1/rounds/002/prompt.md 'recommended next loop build'

repo2="${tmp_root}/wrong-closes"
mkdir -p "${repo2}"
cat > "${repo2}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo2}"
"${RDL}" start research mission.md --session-id wrong > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/wrong/rounds/001/review.md
"${RDL}" decide accept > /dev/null
complete_decision .rdl/sessions/wrong/rounds/001/decision.md accept capability none
assert_fails next-wrong-closes.json "${RDL}" next
assert_file_contains next-wrong-closes.json '"status": "blocked"'
assert_file_contains next-wrong-closes.json '"code":"invalid_closes"'
[[ ! -d .rdl/sessions/wrong/rounds/002 ]] || fail "next advanced despite wrong Closes field"

repo3="${tmp_root}/research-missing-evidence"
mkdir -p "${repo3}"
cat > "${repo3}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo3}"
"${RDL}" start research mission.md --session-id no_evidence > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/no_evidence/rounds/001/review.md
"${RDL}" decide continue > /dev/null
complete_decision .rdl/sessions/no_evidence/rounds/001/decision.md continue claim none
cat > .rdl/sessions/no_evidence/rounds/001/interpretation.md <<'INTERPRETATION'
# Interpretation

Interpretation: present.
INTERPRETATION
assert_fails next-research-missing-evidence.json "${RDL}" next
assert_file_contains next-research-missing-evidence.json '"status": "blocked"'
assert_file_contains next-research-missing-evidence.json '"code":"missing_research_evidence"'
[[ ! -d .rdl/sessions/no_evidence/rounds/002 ]] || fail "next advanced despite missing research evidence"

repo4="${tmp_root}/research-missing-interpretation"
mkdir -p "${repo4}"
cat > "${repo4}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo4}"
"${RDL}" start research mission.md --session-id no_interpretation > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/no_interpretation/rounds/001/review.md
"${RDL}" decide continue > /dev/null
complete_decision .rdl/sessions/no_interpretation/rounds/001/decision.md continue claim none
cat > .rdl/sessions/no_interpretation/rounds/001/evidence.md <<'EVIDENCE'
# Evidence

Research evidence: present.
EVIDENCE
assert_fails next-research-missing-interpretation.json "${RDL}" next
assert_file_contains next-research-missing-interpretation.json '"status": "blocked"'
assert_file_contains next-research-missing-interpretation.json '"code":"missing_interpretation"'
[[ ! -d .rdl/sessions/no_interpretation/rounds/002 ]] || fail "next advanced despite missing interpretation"

repo5="${tmp_root}/build-missing-verification"
mkdir -p "${repo5}"
cat > "${repo5}/mission.md" <<'MISSION'
# Build Mission
MISSION
cd "${repo5}"
"${RDL}" start build mission.md --session-id build_missing > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/build_missing/rounds/001/review.md
"${RDL}" decide accept > /dev/null
complete_decision .rdl/sessions/build_missing/rounds/001/decision.md accept capability none
cat > .rdl/sessions/build_missing/rounds/001/intent.md <<'INTENT'
# Intent

Intent: present.
INTENT
cat > .rdl/sessions/build_missing/rounds/001/work.md <<'WORK'
# Work

Work: present.
WORK
cat > .rdl/sessions/build_missing/rounds/001/evidence.md <<'EVIDENCE'
# Evidence

Evidence exists but only says implementation happened.
EVIDENCE
assert_fails next-build-missing-verification.json "${RDL}" next
assert_file_contains next-build-missing-verification.json '"status": "blocked"'
assert_file_contains next-build-missing-verification.json '"code":"missing_verification_evidence"'
[[ ! -d .rdl/sessions/build_missing/rounds/002 ]] || fail "next advanced despite missing build verification evidence"

repo6="${tmp_root}/build-empty-verification-label"
mkdir -p "${repo6}"
cat > "${repo6}/mission.md" <<'MISSION'
# Build Mission
MISSION
cd "${repo6}"
"${RDL}" start build mission.md --session-id build_empty_label > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/build_empty_label/rounds/001/review.md
"${RDL}" decide accept > /dev/null
complete_decision .rdl/sessions/build_empty_label/rounds/001/decision.md accept capability none
cat > .rdl/sessions/build_empty_label/rounds/001/intent.md <<'INTENT'
# Intent

Intent: present.
INTENT
cat > .rdl/sessions/build_empty_label/rounds/001/work.md <<'WORK'
# Work

Work: present.
WORK
cat > .rdl/sessions/build_empty_label/rounds/001/evidence.md <<'EVIDENCE'
# Evidence

Verification evidence:
EVIDENCE
assert_fails next-build-empty-verification-label.json "${RDL}" next
assert_file_contains next-build-empty-verification-label.json '"status": "blocked"'
assert_file_contains next-build-empty-verification-label.json '"code":"missing_verification_evidence"'
[[ ! -d .rdl/sessions/build_empty_label/rounds/002 ]] || fail "next advanced despite empty verification label"

repo7="${tmp_root}/build-empty-verification-heading"
mkdir -p "${repo7}"
cat > "${repo7}/mission.md" <<'MISSION'
# Build Mission
MISSION
cd "${repo7}"
"${RDL}" start build mission.md --session-id build_empty_heading > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/build_empty_heading/rounds/001/review.md
"${RDL}" decide accept > /dev/null
complete_decision .rdl/sessions/build_empty_heading/rounds/001/decision.md accept capability none
cat > .rdl/sessions/build_empty_heading/rounds/001/intent.md <<'INTENT'
# Intent

Intent: present.
INTENT
cat > .rdl/sessions/build_empty_heading/rounds/001/work.md <<'WORK'
# Work

Work: present.
WORK
cat > .rdl/sessions/build_empty_heading/rounds/001/evidence.md <<'EVIDENCE'
# Evidence

## Verification Evidence

EVIDENCE
assert_fails next-build-empty-verification-heading.json "${RDL}" next
assert_file_contains next-build-empty-verification-heading.json '"status": "blocked"'
assert_file_contains next-build-empty-verification-heading.json '"code":"missing_verification_evidence"'
[[ ! -d .rdl/sessions/build_empty_heading/rounds/002 ]] || fail "next advanced despite empty verification heading"

repo8="${tmp_root}/build-missing-intent"
mkdir -p "${repo8}"
cat > "${repo8}/mission.md" <<'MISSION'
# Build Mission
MISSION
cd "${repo8}"
"${RDL}" start build mission.md --session-id build_no_intent > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/build_no_intent/rounds/001/review.md
"${RDL}" decide accept > /dev/null
complete_decision .rdl/sessions/build_no_intent/rounds/001/decision.md accept capability none
cat > .rdl/sessions/build_no_intent/rounds/001/work.md <<'WORK'
# Work

Work: present.
WORK
cat > .rdl/sessions/build_no_intent/rounds/001/evidence.md <<'EVIDENCE'
# Evidence

Verification evidence: present.
EVIDENCE
assert_fails next-build-missing-intent.json "${RDL}" next
assert_file_contains next-build-missing-intent.json '"status": "blocked"'
assert_file_contains next-build-missing-intent.json '"code":"missing_build_intent"'
[[ ! -d .rdl/sessions/build_no_intent/rounds/002 ]] || fail "next advanced despite missing build intent"

repo9="${tmp_root}/build-missing-work"
mkdir -p "${repo9}"
cat > "${repo9}/mission.md" <<'MISSION'
# Build Mission
MISSION
cd "${repo9}"
"${RDL}" start build mission.md --session-id build_no_work > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/build_no_work/rounds/001/review.md
"${RDL}" decide accept > /dev/null
complete_decision .rdl/sessions/build_no_work/rounds/001/decision.md accept capability none
cat > .rdl/sessions/build_no_work/rounds/001/intent.md <<'INTENT'
# Intent

Intent: present.
INTENT
cat > .rdl/sessions/build_no_work/rounds/001/evidence.md <<'EVIDENCE'
# Evidence

Verification evidence: present.
EVIDENCE
assert_fails next-build-missing-work.json "${RDL}" next
assert_file_contains next-build-missing-work.json '"status": "blocked"'
assert_file_contains next-build-missing-work.json '"code":"missing_build_work"'
[[ ! -d .rdl/sessions/build_no_work/rounds/002 ]] || fail "next advanced despite missing build work"

repo10="${tmp_root}/build"
mkdir -p "${repo10}"
cat > "${repo10}/mission.md" <<'MISSION'
# Build Mission
MISSION
cd "${repo10}"
"${RDL}" start build mission.md --session-id build1 > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/build1/rounds/001/review.md
"${RDL}" decide accept > /dev/null
complete_decision .rdl/sessions/build1/rounds/001/decision.md accept capability research
add_build_round_records .rdl/sessions/build1/rounds/001
"${RDL}" next > next-build.json
assert_file_contains next-build.json '"status": "ok"'
assert_file_contains next-build.json '"mode": "build"'
assert_file_contains next-build.json '"round": 2'
assert_file_contains .rdl/sessions/build1/state.json '"mode": "build"'
assert_file_contains .rdl/sessions/build1/rounds/002/prompt.md 'Mode: build'
assert_file_contains .rdl/sessions/build1/rounds/002/prompt.md 'recommended next loop research'

echo "round2 tests ok"

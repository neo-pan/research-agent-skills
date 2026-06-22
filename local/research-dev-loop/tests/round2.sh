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

repo3="${tmp_root}/build-missing-verification"
mkdir -p "${repo3}"
cat > "${repo3}/mission.md" <<'MISSION'
# Build Mission
MISSION
cd "${repo3}"
"${RDL}" start build mission.md --session-id build_missing > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/build_missing/rounds/001/review.md
"${RDL}" decide accept > /dev/null
complete_decision .rdl/sessions/build_missing/rounds/001/decision.md accept capability none
cat > .rdl/sessions/build_missing/rounds/001/evidence.md <<'EVIDENCE'
# Evidence

Evidence exists but only says implementation happened.
EVIDENCE
assert_fails next-build-missing-verification.json "${RDL}" next
assert_file_contains next-build-missing-verification.json '"status": "blocked"'
assert_file_contains next-build-missing-verification.json '"code":"missing_verification_evidence"'
[[ ! -d .rdl/sessions/build_missing/rounds/002 ]] || fail "next advanced despite missing build verification evidence"

repo3="${tmp_root}/build"
mkdir -p "${repo3}"
cat > "${repo3}/mission.md" <<'MISSION'
# Build Mission
MISSION
cd "${repo3}"
"${RDL}" start build mission.md --session-id build1 > /dev/null
"${RDL}" review > /dev/null
complete_review .rdl/sessions/build1/rounds/001/review.md
"${RDL}" decide accept > /dev/null
complete_decision .rdl/sessions/build1/rounds/001/decision.md accept capability research
cat > .rdl/sessions/build1/rounds/001/evidence.md <<'EVIDENCE'
# Evidence

Verification evidence: fixture capability check passed.
EVIDENCE
"${RDL}" next > next-build.json
assert_file_contains next-build.json '"status": "ok"'
assert_file_contains next-build.json '"mode": "build"'
assert_file_contains next-build.json '"round": 2'
assert_file_contains .rdl/sessions/build1/state.json '"mode": "build"'
assert_file_contains .rdl/sessions/build1/rounds/002/prompt.md 'Mode: build'
assert_file_contains .rdl/sessions/build1/rounds/002/prompt.md 'recommended next loop research'

echo "round2 tests ok"

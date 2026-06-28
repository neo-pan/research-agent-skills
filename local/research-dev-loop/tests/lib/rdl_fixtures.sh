#!/usr/bin/env bash

rdl_write_complete_review() {
  local file="$1"
  local recommended="${2:-continue}"
  local verdict="${3:-PASS}"
  local decision_reviewed="${4:-pending}"
  cat > "${file}" <<REVIEW
# Review

Reviewer: fixture
Review Mode: manual
Review Scope: current round
Artifacts Reviewed: prompt, evidence, decision
Verdict: ${verdict}
Decision Reviewed: ${decision_reviewed}
Evidence Reviewed: fixture evidence
Blocking Evidence Gaps: none
Implementation Findings: none
Evaluation Integrity Findings: acceptable
Overclaim Risks: bounded
Readiness Level: ready
Recommended Decision: ${recommended}

REVIEW
}

rdl_write_complete_decision() {
  local file="$1"
  local decision="$2"
  local closes="$3"
  local next_loop="${4:-none}"
  local next_step="${5:-continue same mode}"
  local evidence="${6:-fixture evidence}"
  cat > "${file}" <<DECISION
# Decision

Decision: ${decision}
Closes: ${closes}
Evidence: ${evidence}
Uncertainty: bounded
What this rules out: unsupported alternatives
What remains unknown: later work
Recommended next loop: ${next_loop}
Next smallest step: ${next_step}

DECISION
}

rdl_write_artifact_manifest() {
  local file="$1"
  local artifact_id="${2:-E1}"
  local artifact_path="${3:-artifacts/check.log}"
  local description="${4:-Fixture evidence artifact}"
  local round="${5:-1}"
  cat > "${file}" <<MANIFEST
{
  "artifacts": [
    {
      "id": "${artifact_id}",
      "kind": "log",
      "path": "${artifact_path}",
      "round": ${round},
      "description": "${description}"
    }
  ]
}
MANIFEST
}

rdl_write_research_evidence() {
  local round_dir="$1"
  local cite_artifact="${2:-no}"
  if [[ "${cite_artifact}" == "yes" ]]; then
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
  else
    cat > "${round_dir}/evidence.md" <<'EVIDENCE'
# Evidence

Research evidence: fixture claim evidence.

## Evaluation Integrity

Manual fixture integrity reviewed.

## Missing Evidence

No blocking missing evidence for this fixture.

## Evidence Budget

One local fixture check.
EVIDENCE
  fi

  cat > "${round_dir}/interpretation.md" <<'INTERPRETATION'
# Interpretation

Interpretation: fixture evidence supports the next research step.
INTERPRETATION
}

rdl_write_build_evidence() {
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

## Evaluation Integrity

Manual fixture integrity reviewed.

## Missing Evidence

No blocking missing evidence for this fixture.

## Evidence Budget

One local fixture check.
EVIDENCE
  else
    cat > "${round_dir}/evidence.md" <<'EVIDENCE'
# Evidence

Evidence exists but no verification is recorded.

## Evaluation Integrity

Manual fixture integrity reviewed.

## Missing Evidence

No blocking missing evidence for this fixture.

## Evidence Budget

One local fixture check.
EVIDENCE
  fi
}

rdl_write_final_report() {
  local file="$1"
  local outcome="$2"
  local closed="${3:-fixture claim}"
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

rdl_write_ready_progress() {
  local file="$1"
  local include_nonblocking_question="${2:-yes}"
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
  if [[ "${include_nonblocking_question}" == "yes" ]]; then
    cat >> "${file}" <<'PROGRESS'
| Is release timing known? | fixture | no | Non-blocking follow-up. |
PROGRESS
  fi
}

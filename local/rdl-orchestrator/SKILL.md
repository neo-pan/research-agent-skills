---
name: rdl-orchestrator
description: Manual RDL-backed orchestration workflow for driving research or build rounds with dedicated writer and reviewer subagents.
disable-model-invocation: true
---

# RDL Orchestrator

Drive an existing RDL-backed research or build session across rounds until the
session closes or a real blocker requires stopping.

This skill is user-invoked only. Subagents are required for this workflow; if
round-writer or semantic-review subagents cannot be created, stop and report the
tooling blocker instead of continuing in the main agent.

RDL remains a file protocol and CLI, not a runtime supervisor. Do not change RDL
core commands, protocol files, or Python implementation as part of this
workflow.

## Round Lifecycle

At the start of each non-closed round, reread this skill contract before doing
project work.

1. Take over RDL state.
   - Run `rdl handoff --json`.
   - Run `rdl doctor --json`.
   - Read `prompt.md`, `mission.md`, `progress.md`, `factors.md`,
     `decision-ledger.md`, and previous round evidence and decision records
     when present.
   - Completion check: current session, current round, gate status, active
     work, known blockers, and next step are understood.

2. Execute the current plan step.
   - Perform the current `Next Smallest Step` or equivalent plan step.
   - Collect raw results, artifact facts, verification notes, and blockers.
   - Completion check: there is concrete material for a writer to record, or a
     blocker that can be faithfully recorded.

3. Spawn one round-writer subagent for the current writer pass.
   - Provide RDL state, prompt, mission, prior context, raw results, artifact
     facts, verification notes, and blockers.
   - The writer creates a reviewable current-round state by writing evidence,
     work or interpretation records, artifact manifest entries, progress or
     factor memory, and a decision record as needed.
   - The writer uses `rdl progress` and `rdl factors` when possible instead of
     hand-editing those records.
   - Completion check: current-round records are reviewable and no gate or
     transition command has been run by the writer.

4. Create the semantic review pack.
   - Run `rdl review --pack --json`.
   - Completion check: the pack reflects the writer-produced current-round
     state.

5. Spawn one semantic-review subagent.
   - Provide only the review pack and any explicitly supplied verification
     artifacts.
   - Require structured findings, a verdict recommendation, evidence gaps,
     staleness risk, and overclaim risks.
   - Completion check: reviewer has returned findings and made no file edits.

6. Return review findings to the same round writer.
   - The writer writes `review.md`.
   - The writer applies necessary record corrections from accepted review
     findings.
   - The writer may run read-only checks such as `rdl doctor --json`.
   - Completion check: review findings and accepted corrections are recorded,
     then the writer closes.

7. Run the gate and transition.
   - Run `rdl doctor --json`.
   - If a close decision is valid, run `rdl close --json`.
   - If advance is valid, run `rdl next --json`.
   - If blocked and fixable, do more plan work in the same round and repeat the
     writer/review sequence with a new round-local writer if the previous writer
     has closed.
   - If blocked and not fixable, have a writer record the blocker if possible,
     then stop and report the blocker.
   - Completion check: the session is closed, advanced, or stopped with a
     recorded blocker.

## Role And Write Constraints

| Role | Reads | Writes | Forbidden |
| --- | --- | --- | --- |
| Main agent | RDL records and project context | Project work artifacts when needed | Canonical RDL round files |
| Round writer subagent | RDL state, raw results, review findings | Current-round RDL records, session memory, artifact manifest | `rdl next`, `rdl close`, `state.json`, `gate-report.json`, `gate.md`, `decision-ledger.md` |
| Semantic review subagent | Review pack and explicit verification artifacts | Nothing | Any file edit |

- Every subagent is round-local or review-local and closes after its assigned
  work.
- Each round has exactly one canonical RDL writer at a time.
- The main agent runs RDL gate and transition commands, but does not directly
  edit canonical RDL round files.
- Semantic review remains separate from deterministic gate checks and stays
  read-only.

## Stop Conditions

Stop when any of these conditions applies:

- `rdl close --json` succeeds.
- `rdl doctor --json` or `rdl next --json` is blocked and the main agent cannot
  resolve the blocker through more work.
- The writer cannot faithfully record evidence, artifact facts, or blockers.
- Review findings require a direction change, unavailable evidence, or user or
  project input.
- RDL protocol or gate files are damaged and require user intervention.

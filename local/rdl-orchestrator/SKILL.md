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
For RDL CLI and protocol details, use `research-dev-loop` as the source of
truth.

## Round Lifecycle

At the start of each non-closed round, reread this skill contract before doing
project work.

1. Take over RDL state.
   - Run `rdl handoff --json`.
   - Run `rdl doctor --json`.
   - When consuming JSON output, use a clean invocation and retry cleanly if
     stdout contains shell startup text or other non-JSON noise.
   - Read `prompt.md`, `mission.md`, `progress.md`, `factors.md`,
     `decision-ledger.md`, current-round `intent.md` or `work.md` when present,
     and previous round evidence and decision records when present.
   - Identify the current mission slice from `progress.md#Active`,
     round-local prompt or intent, and the latest decision. If the mission is
     broad and no active slice is explicit, do not start project work yet.
   - Completion check: current session, current round, gate status, active
     work, current slice if present, known blockers, and next step are
     understood.

2. Establish the mission slice when missing.
   - Use this step only when takeover found a broad mission without an explicit
     active slice.
   - Spawn the round's canonical writer subagent if it is not already open. The
     writer reads RDL records and project context, summarizes the mission shape,
     and records a minimal slice plan before project work.
   - Give the writer the mission boundary and relevant context pointers, not
     prewritten per-file content. The writer should preserve the original
     mission and record: horizontal slices as independent workstreams or
     evidence areas, vertical slices as smallest evidence-producing steps,
     exactly one current active slice, deferred slices, blockers, and the
     review trigger for the current slice.
   - Prefer `rdl progress active|blocked|deferred|none` and `rdl factors`
     records over a new todo file. Use round `intent.md` or `work.md` only when
     the current mode requires implementation detail.
   - The writer must not edit `mission.md` unless the mission itself has
     changed, and must not run `rdl next`, `rdl close`, or gate transitions.
   - Reread `rdl handoff --json`, `progress.md`, and relevant round records
     after the writer records the slice. Later execution results must be
     returned to the same round writer.
   - Completion check: there is one explicit active slice with a concrete
     review trigger, or a blocker is recorded and project work stops.

3. Execute the current plan step.
   - Perform the current `Next Smallest Step` or equivalent plan step.
   - Keep execution inside the current active slice unless new evidence makes
     the slice invalid; if it does, stop project work and have a writer record
     the blocker or direction change.
   - Collect raw results, artifact facts, verification notes, and blockers.
   - Completion check: there is concrete material for a writer to record, or a
     blocker that can be faithfully recorded.

4. Use the round writer to record current-round state.
   - Spawn the round's canonical writer subagent if it is not already open, then
     reuse that same writer for every write task until the round advances,
     closes, or stops.
   - Provide RDL state pointers, prompt, mission, prior context pointers, raw
     results, artifact facts, verification notes, and blockers. Do not provide
     exact target text for each RDL file unless the user supplied that text or a
     protocol field requires a literal value.
   - The writer reads the supplied context and relevant files, summarizes the
     current state, and creates a reviewable current-round state by writing
     evidence, work or interpretation records, artifact manifest entries,
     progress or factor memory, and a decision record as needed.
   - The writer uses `rdl progress` and `rdl factors` when possible instead of
     hand-editing those records.
   - The writer runs or consumes `rdl memory --check --json` and corrects
     protocol-level session-memory gaps before review. Judgment-heavy memory
     changes remain explicit writer decisions, not automatic summary edits.
   - Completion check: current-round records are reviewable, the same round
     writer remains available for review findings, and no gate or transition
     command has been run by the writer.

5. Create the semantic review pack.
   - Run `rdl review --pack --json`.
   - Ensure the pack's reviewer task is action/profile/mode-aware and concise;
     do not add extra reviewer ceremony outside the RDL review flow.
   - Completion check: the pack reflects the writer-produced current-round
     state.

6. Spawn one semantic-review subagent.
   - Provide only the review pack and any explicitly supplied verification
     artifacts.
   - Require structured findings, a verdict recommendation, evidence gaps,
     staleness risk, overclaim risks, and whether top-level session memory
     faithfully supports handoff. When a slice plan exists, require the
     reviewer to judge whether the active slice and deferred slices are
     coherent with the mission and current evidence.
   - Completion check: reviewer has returned findings and made no file edits.

7. Return review findings to the round writer.
   - The writer writes `review.md`.
   - In the orchestrated path, the writer records `Review Mode: subagent`
     unless the user explicitly supplied an external adapter result.
   - The writer records returned findings in `Returned Review Findings` using
     `- severity | category | location | claim | required_resolution`.
   - The writer rereads the affected records and applies necessary record
     corrections from accepted review findings.
   - The writer records accepted corrections separately from returned findings.
   - The writer may run read-only checks such as `rdl doctor --json`.
   - If accepted findings identify stale, fragmented, or incomplete handoff
     memory, the writer updates `progress.md` or `factors.md` explicitly and
     reruns `rdl memory --check --json` before closing.
   - Completion check: review findings and accepted corrections are recorded,
     and the round writer remains open until the gate transition or stop result
     for this round is known.

8. Run the gate and transition.
   - Run `rdl doctor --json`.
   - If a close decision is valid, run `rdl close --json`.
   - If advance is valid, run `rdl next --json`.
   - If blocked and fixable, do more plan work in the same round and repeat the
     writer/review sequence with the same round writer.
   - If blocked and not fixable, have a writer record the blocker if possible,
     then stop and report the blocker.
   - Close the round writer only after the round advances, closes, or stops.
   - Completion check: the session is closed, advanced, or stopped with a
     recorded blocker.

## Role And Write Constraints

| Role | Reads | Writes | Forbidden |
| --- | --- | --- | --- |
| Main agent | RDL records and project context | Project work artifacts when needed | Canonical RDL round files |
| Round writer subagent | RDL state, raw results, review findings | Current-round RDL records, session memory, artifact manifest | `rdl next`, `rdl close`, `state.json`, `gate-report.json`, `gate.md`, `decision-ledger.md` |
| Semantic review subagent | Review pack and explicit verification artifacts | Nothing | Any file edit |

- The round writer is round-local and remains open across all write tasks in
  that round until the round advances, closes, or stops.
- Semantic review subagents are review-local and close after their assigned
  work.
- Each round has exactly one canonical RDL writer. The same writer handles
  slice planning, evidence and decision records, review incorporation, blocker
  records, and session-memory updates for that round.
- The main agent runs RDL gate and transition commands, but does not directly
  edit canonical RDL round files.
- The main agent provides raw results, artifact facts, verification notes, and
  pointers to relevant context. The writer reads, summarizes, and decides the
  specific RDL file contents to write.
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

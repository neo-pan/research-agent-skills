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
typed tooling blocker instead of continuing in the main agent.

RDL remains a file protocol and CLI, not a runtime supervisor. Do not change RDL
core commands, protocol files, or Python implementation as part of this
workflow.
For RDL CLI and protocol details, use `research-dev-loop` as the source of
truth.

## Core Terms

A compact slice contract names the objective, smallest evidence-producing step,
expected artifacts, validation command or check, review trigger, and abort
condition for the current active slice.

A typed blocker records the blocker type, cause, attempted resolution, and
required external input. Use the closest type: tooling, permission,
environment, evidence, design, semantic review, or scope.

## Write Shape

Keep writer judgment separate from RDL shape.

- The round writer owns judgment: claims, evidence meaning, uncertainty,
  blocker type, accepted corrections, and justified decisions.
- RDL owns shape: templates, canonical headings, table columns, managed
  summaries, JSON, gate artifacts, and integrity records.
- The main agent gives the writer facts, constraints, artifacts, and pointers,
  then points to CLI helpers or templates for shape.
- Prefer `rdl progress`, `rdl factors`, and `rdl record` when they can express
  the record.
- For artifacts, the writer supplies an existing local file path or an
  `http(s)` URL to `rdl record artifact`; RDL records manifest shape and local
  size/hash.
- Use hand edits for semantic content that structured RDL commands cannot
  express. If canonical shape is damaged, surface the protocol blocker.

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
     round-local prompt or intent, and the latest decision. Verify that any
     existing active slice has a compact slice contract or equivalent record.
     If the mission is broad and no active slice is explicit, do not start
     project work yet.
   - Identify the autonomy envelope for this session or round: allowed scope,
     forbidden actions, approval-required actions, any time, token, round, or
     risk budget, expected final artifact or stopping state, and evidence
     threshold for the current mission.
   - When there is evidence of interruption, compaction, resumed work, or
     unclear state, inspect the last successful `rdl next` or `rdl close`, the
     last repository persistence check when present, open review findings and
     accepted corrections, and whether assumptions about writer or reviewer
     state still hold. If recovery state is ambiguous, stop before project work
     and report the ambiguity.
   - Completion check: current session, current round, gate status, active
     work, current slice if present, known blockers, next step, autonomy
     envelope, active slice contract when present, and clean, resumed, or
     blocked recovery status are understood.

2. Establish the mission slice when missing.
   - Use this step only when takeover found a broad mission without an explicit
     active slice.
   - Spawn the round's canonical writer subagent if it is not already open. The
     writer reads RDL records and project context, summarizes the mission shape,
     and records a minimal slice plan before project work.
   - Give the writer the mission boundary and relevant context pointers, not
     prewritten per-file content. The writer should preserve the original
     mission and record horizontal slices as independent workstreams or
     evidence areas, vertical slices as smallest evidence-producing steps,
     deferred slices, and typed blockers.
   - The writer records exactly one current active slice with a compact slice
     contract.
   - Prefer `rdl progress active|blocked|deferred|none` and `rdl factors`
     records over a new todo file. Use round `intent.md` or `work.md` only when
     the current mode requires implementation detail.
   - The writer must not edit `mission.md` unless the mission itself has
     changed, and must not run `rdl next`, `rdl close`, or gate transitions.
   - Reread `rdl handoff --json`, `progress.md`, and relevant round records
     after the writer records the slice. Later execution results must be
     returned to the same round writer.
   - Completion check: there is one explicit active slice with a compact slice
     contract that another agent could execute without rereading the full
     mission history, or a typed blocker is recorded and project work stops.

3. Inspect repository state before editing.
   - Use this step before project work in each non-closed round.
   - If the project is in a Git repository, run `git status --short`.
   - Classify the changed-file surface as existing user changes,
     pre-existing or uncertain changes, RDL or session changes, project
     changes from the current loop, generated or disposable artifacts, and
     untracked files that may be relevant to the slice.
   - Identify files that must be avoided or protected during the current
     slice.
   - Keep this step to inspection and classification. Stage, commit, clean, or
     discard files only when explicitly requested or when a later persistence
     step permits it.
   - Completion check: repository state is visible when Git is available, file
     ownership is classified enough to edit safely, and protected files are
     known before project work begins.

4. Execute the current plan step.
   - Perform the current `Next Smallest Step` or equivalent plan step.
   - Keep execution inside the current active slice unless new evidence makes
     the slice invalid; if it does, stop project work and have a writer record
     the typed blocker or direction change.
   - Choose and collect the strongest feasible verification evidence for the
     slice: static inspection, unit test, integration test, end-to-end or
     manual check. Use `semantic review only` or `cannot verify` only when no
     stronger direct verification is feasible, and record the reason.
   - Collect raw results, artifact facts, verification level, command or
     evidence, result, residual gap or risk, and typed blockers.
   - Completion check: there is concrete material for a writer to record,
     including verification strength and residual gap, or a typed blocker that
     can be faithfully recorded.

5. Use the round writer to record current-round state.
   - Spawn the round's canonical writer subagent if it is not already open, then
     reuse that same writer for every write task until the round advances,
     closes, or stops.
   - Provide RDL state pointers, prompt, mission, prior context pointers, raw
     results, artifact facts, verification level, command or evidence, result,
     fallback outcome when used, residual gap or risk, and typed blockers. Do
     not provide exact target text for each RDL file unless the user supplied
     that text or a protocol field requires a literal value.
   - The writer reads the supplied context and relevant files, summarizes the
     current state, and creates a reviewable current-round state by writing
     evidence, work or interpretation records, artifact manifest entries,
     progress or factor memory, and a decision record as needed.
   - The writer uses `rdl progress` and `rdl factors` when possible instead of
     hand-editing those records.
   - The writer runs or consumes `rdl memory --check --json` and corrects
     protocol-level session-memory gaps before review. Judgment-heavy memory
     changes remain explicit writer decisions, not automatic summary edits.
   - Completion check: current-round records are reviewable, verification
     strength and residual gaps are recorded, the same round writer remains
     available for review findings, and no gate or transition command has been
     run by the writer.

6. Create the semantic review pack.
   - Run `rdl review --pack --json`.
   - Ensure the pack's reviewer task is action/profile/mode-aware and concise;
     do not add extra reviewer ceremony outside the RDL review flow.
   - Completion check: the pack reflects the writer-produced current-round
     state.

7. Spawn one semantic-review subagent.
   - Provide only the review pack and any explicitly supplied verification
     artifacts.
   - Require structured findings, a verdict recommendation, evidence gaps,
     staleness risk, overclaim risks, and whether top-level session memory
     faithfully supports handoff. When a slice plan exists, require the
     reviewer to judge whether the active slice and deferred slices are
     coherent with the mission and current evidence.
   - Completion check: reviewer has returned findings and made no file edits.

8. Return review findings to the round writer.
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

9. Run the gate and transition.
   - Run `rdl doctor --json`.
   - If a close decision is valid, run `rdl close --json`.
   - If advance is valid, run `rdl next --json`.
   - If blocked and fixable, do more plan work in the same round and repeat the
     writer/review sequence with the same round writer.
   - If blocked and not fixable, have a writer record the typed blocker if
     possible, then stop and report the blocker and required external input.
   - Close the round writer only after the round advances, closes, or stops.
   - Completion check: the session is closed, advanced, or stopped with a
     recorded typed blocker when stopped, and the repository persistence check
     is still pending after a successful close or advance.

10. Run the repository persistence check.
   - Use this step only after `rdl next --json` or `rdl close --json`
     succeeds.
   - Confirm RDL records, project artifacts, and verification outputs from the
     completed round are saved.
   - If the project is in a Git repository, run `git status --short` and review
     the changed-file surface before reporting the boundary state.
   - Stage or commit changes only when the user explicitly requests it, or when
     standing project permission allows it and the changed-file surface has been
     reviewed.
   - Report whether a commit is recommended when saved code, research outputs,
     or RDL records form a useful recovery boundary.
   - Completion check: saved artifacts are accounted for, repository state is
     visible when Git is available, and any commit action or recommendation is
     explicit.

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
  slice planning, evidence and decision records, review incorporation, typed
  blocker records, and session-memory updates for that round.
- The main agent runs RDL gate and transition commands, but does not directly
  edit canonical RDL round files.
- The main agent or user handles repository-level persistence. Round writer and
  semantic review subagents do not stage or commit changes.
- The main agent provides raw results, artifact facts, verification level,
  command or evidence, result, residual gap, typed blockers, and pointers to
  relevant context. The writer reads, summarizes, and decides the specific RDL
  file contents to write.
- Writer prompts preserve the write-shape boundary: the writer decides meaning;
  RDL helpers and templates carry canonical structure where available.
- Semantic review remains separate from deterministic gate checks and stays
  read-only.

## Escalation Boundaries

Pause and ask before destructive operations, approval-required dependency or
network work, staging, committing, publishing, or pushing without authorization,
work outside the active slice, mission or product direction changes, proceeding
after contradictory evidence, or continuing after repeated failed attempts.

## Stop Conditions

Stop when any of these conditions applies:

- `rdl close --json` succeeds and the repository persistence check is reported.
- `rdl doctor --json` or `rdl next --json` is blocked and the main agent cannot
  resolve the typed blocker through more work.
- The writer cannot faithfully record evidence, artifact facts, or typed
  blockers.
- Review findings require a direction change, unavailable evidence, or user or
  project input.
- RDL protocol or gate files are damaged and require user intervention.

When stopping on a typed blocker, report the blocker type, cause, attempted
resolution, and required external input.

## Final Reporting

Before the final response for an orchestrated run, confirm and summarize the
closure or stop status, repository persistence state, verification, remaining
risks, final artifact paths, and whether any required subagent task remains
open.

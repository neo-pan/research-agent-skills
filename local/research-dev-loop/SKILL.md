---
name: research-dev-loop
description: RDL evidence-backed research loop. Use when a research or research-engineering task needs durable mission, evidence, uncertainty, review, decision, or handoff records.
---

# Research Development Loop

Use RDL when research work must preserve claims, evidence, missing evidence,
uncertainty, decisions, and handoff state across rounds.

RDL is a small file protocol and CLI, not a project runtime supervisor. It
records state under `.rdl/sessions/<session-id>/` and indexes external artifacts
by reference. It does not own project source files, git state, CI state,
experiment queues, benchmark runners, or deployment state.

For user-invoked multi-round orchestration, use `rdl-orchestrator`; keep this
skill focused on the RDL protocol and CLI.

## Core Loop

1. Start or take over a session.
   - Use `rdl start ... --json` for a new mission, or `rdl handoff --json` as
     the first read-only status surface for an existing session.
   - Completion check: the active session, current round, current mode/profile,
     gate status, active work, blockers, and next step are understood.

2. Read the round state before project work.
   - Read `mission.md`, `progress.md`, `factors.md`, `decision-ledger.md`, and
     current or previous round evidence and decision records when present.
   - Completion check: the current claim or capability under review and the
     smallest evidence-producing step are explicit, or the missing slice/blocker
     is recorded before work continues.

3. Record evidence and decisions before advancing.
   - Open or advance a round only when there is a concrete claim or capability
     to review. Do not advance just because a command ran, a directory was
     created, or the next step is unchanged.
   - Completion check: decision-grade evidence, uncertainty, what remains
     unknown, and the next smallest step are recorded in the current round.

4. Keep session memory recoverable.
   - Update `progress.md` and `factors.md` when completed work, active claims or
     capabilities, blockers, open questions, directions tried, datasets,
     workloads, baselines, metrics, validators, prompts, backends, hardware, or
     nondeterminism change.
   - Completion check: `rdl handoff` can recover the current state without
     relying on conversation memory.

5. Run semantic review through the RDL review flow when the gate requires it.
   - Use `rdl review --pack --for next|close|doctor --json` to produce a clean,
     action-aware context pack. Use generic `rdl review --pack --json` only when
     no intended action is known or compatibility requires it. Review
     adapters include independent subagents, `phase-review`, manual review, and
     project reviewers. The orchestrated path defaults to subagents; the base
     RDL protocol accepts any explicit adapter recorded in `review.md`.
   - Completion check: review findings and accepted corrections are recorded in
     `review.md`, while judgment-heavy changes to `decision.md`, `progress.md`,
     and `factors.md` remain accepted by the main agent or user.

6. Gate and transition.
   - Use `rdl doctor --json` before `rdl next --json` or `rdl close --json`.
   - Completion check: the session is advanced, closed, or stopped with a
     recorded blocker.

## Reference Pointers

- For command examples, JSON hygiene, requirements, and repo checks, read
  [CLI.md](CLI.md).
- For profile selection, deterministic gate boundaries, `next`, `close`, and
  guard behavior, read [GATES.md](GATES.md).
- For `progress.md`, `factors.md`, handoff, mission slices, and memory checks,
  read [SESSION_MEMORY.md](SESSION_MEMORY.md).
- For review packs, adapters, `review.md`, semantic findings, and staleness
  handling, read [SEMANTIC_REVIEW.md](SEMANTIC_REVIEW.md).
- For artifact citations, `artifact-manifest.json`, and `events.md`, read
  [ARTIFACTS.md](ARTIFACTS.md).

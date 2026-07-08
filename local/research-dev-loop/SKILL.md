---
name: research-dev-loop
description: Lightweight evidence-backed Research Development Loop for AI/ML research development. Use when a research or research-engineering task needs explicit mission, evidence, uncertainty, review, and decision records.
---

# Research Development Loop

Use RDL when a research task should preserve claims, evidence, missing evidence,
uncertainty, and decisions across rounds.

RDL is a small file protocol and CLI, not a project runtime supervisor. It
records research state under `.rdl/sessions/<session-id>/` and indexes external
artifacts by reference. It does not own project source files, git state, CI
state, experiment queues, benchmark runners, or deployment state.

For user-invoked multi-round orchestration, use `rdl-orchestrator`; keep this
skill focused on the RDL protocol and CLI.

## CLI

Run the Python module from a project repository:

```bash
PYTHONPATH=local/research-dev-loop python3 -m rdl start research mission.md --json
PYTHONPATH=local/research-dev-loop python3 -m rdl start build plan.md --json
PYTHONPATH=local/research-dev-loop python3 -m rdl status --json
PYTHONPATH=local/research-dev-loop python3 -m rdl handoff --json
PYTHONPATH=local/research-dev-loop python3 -m rdl handoff --session-id <id> --json
PYTHONPATH=local/research-dev-loop python3 -m rdl review --pack --json
PYTHONPATH=local/research-dev-loop python3 -m rdl review --pack --session-path <path> --json
PYTHONPATH=local/research-dev-loop python3 -m rdl memory --check --json
PYTHONPATH=local/research-dev-loop python3 -m rdl next --mode build --json
PYTHONPATH=local/research-dev-loop python3 -m rdl next --profile checkpoint --json
PYTHONPATH=local/research-dev-loop python3 -m rdl progress active --item parser --text "raw parser capability" --trigger "sample coverage review" --json
PYTHONPATH=local/research-dev-loop python3 -m rdl factors --section "Dataset or Workload" --value "current workload slice" --json
```

When another tool or agent consumes `--json`, run RDL from a clean shell/session
so stdout remains parseable JSON.

## Requirements

RDL requires `python3`. Its implementation lives under
`local/research-dev-loop/rdl/`.

The manual profile should remain usable without hooks. Guarded operation, when
implemented, should call `rdl guard-stop` as thin transport and keep all RDL
logic inside the CLI.

## Checks

Use `./scripts/check.sh` before committing changes. It runs manifest/link
checks, RDL Python tests, and repository prerequisite checks.

## Principles

- Keep one active RDL session per repository.
- Open or advance a round only when there is a concrete claim or capability to
  review. Do not advance a round just because a command ran, a directory was
  created, or the next step is unchanged.
- Record decision-grade evidence before advancing or closing decisions.
- Separate research claim closure from research capability closure.
- Use `rdl next --mode build` or `rdl next --mode research` when the next round
  should change loop type. `Recommended next loop` records intent, but does not
  by itself switch mode.
- `rdl close` can infer `positive`, `negative`, or `inconclusive` from a
  current `Decision: close-*` record. Pass an explicit outcome only when the
  close decision is not already recorded or when checking a specific outcome.
- Use `--profile full-review` for phase gates, go/no-go decisions, and closing
  rounds. Use `--profile checkpoint` for compact evidence+decision checkpoints.
  Use `--profile build-update` only in build mode for compact capability work
  updates. If no profile is supplied, RDL keeps the current profile and defaults
  new sessions to `full-review`.
- Lightweight profiles reduce round boilerplate; they do not remove the need for
  decision-grade evidence, `decision.md`, artifact discipline, or session-memory
  updates when state changes.
- Use optional round-local `events.md` for operational events that matter for
  recovery but are not decision-grade evidence: command timeouts, partial
  transfers, retries, cache or working-directory requirements, and environment
  notes. Keep `evidence.md` focused on evidence that changes a claim or
  capability decision.
- Treat `.rdl/sessions/<session-id>/` as the recoverable state; do not depend on
  conversation memory for claims, evidence, open questions, or next steps.
- Use `rdl handoff` or `rdl handoff --json` as the first read-only status
  surface when taking over an existing long-running session.
- Use `--session-id` or `--session-path` with read-only check surfaces when
  auditing a historical or closed session instead of the active session.
- At the start of a round, read `mission.md`, `progress.md`, `factors.md`,
  `decision-ledger.md`, and the previous round's decision/evidence records when
  they exist.
- Before running `rdl next`, update `progress.md` and `factors.md` when the
  round changes completed work, active claims or capabilities, blockers, open
  questions, directions tried, datasets, workloads, baselines, metrics,
  validators, prompts, backends, hardware, or nondeterminism.
- When a broad mission needs decomposition, record the current mission slice in
  `progress.md` and supporting context in `factors.md` or round records. Treat
  slice quality, ordering, and completeness as semantic review concerns, not
  deterministic gate rules.
- Use `rdl progress active|blocked|deferred|none` and `rdl factors` to
  explicitly maintain top-level session memory
  without hand-editing Markdown tables.
- `rdl progress active` defaults to the current session mode and
  `--blocking no`; pass `--mode` or `--blocking yes` only when they differ.
- `rdl factors --section ... --value ...` defaults to `set`; use
  `rdl factors note` to append a factor note instead of replacing the section.
- Use `rdl memory --check` when `doctor` reports weak session memory or a
  session has run for multiple rounds. Use `rdl memory --write` only to refresh
  deterministic managed summary blocks; still update active, blocked, deferred,
  and factor records manually when they require judgment.
- Keep deterministic gates limited to protocol, schema, local artifact
  integrity, and managed-summary facts. Do not encode semantic judgments such as
  whether evidence is decision-grade, an active item is truly stale, or a claim
  overreaches as ad hoc parser rules.
- Use `rdl review --pack --json` to produce a clean context pack for a reviewer
  agent. The pack includes RDL records, artifact manifest facts, deterministic
  findings, reviewer instructions, a finding schema, and semantic signals that
  require judgment. It must not create or modify `review.md`.
- Keep semantic-review prompts concise but action/profile/mode-aware. Ask the
  reviewer for a verdict recommendation, memory fidelity, next-action
  recommendation, and short structured findings using the review-pack schema.
- Treat semantic review as part of the default gate contract for `full-review`,
  close, and phase-gate cases. Semantic findings should be produced from the
  review pack or a completed adapter review and surfaced through normal
  `rdl review`, `rdl doctor`, `rdl next`, and `rdl close` flows, not as a
  separate remembered ceremony.
- The first semantic adapter is read-only over completed `review.md` records.
  It surfaces the adapter, reviewed artifacts, staleness/evidence risk, and
  review-blocking findings through `details["gate"]["semantic"]`.
- Successful `rdl next`, `rdl close`, and `rdl guard-stop` transitions write
  round-local `gate-report.json` and `gate.md` audit artifacts for the gate that
  allowed the transition. `rdl doctor` and `rdl handoff` remain read-only.
- Use independent subagents as the default clean-context semantic review
  adapters. Give them RDL records, relevant artifacts, deterministic gate
  findings, and verification evidence; do not rely on the main conversation
  history as review context. If a subagent cannot be created, stop and report
  the tooling blocker; do not continue semantic review in the main agent or
  record a manual adapter.
- Treat exact repeated next steps and missing recent artifact entries as
  semantic review signals, not as standalone deterministic gate warnings. A
  reviewer agent should judge whether they are harmless continuation, stale
  direction reuse, or insufficient evidence capture.
- Keep canonical RDL files single-writer. Subagents may inspect context and
  produce findings, but the main agent or user must decide which
  judgment-heavy changes to record in `review.md`, `decision.md`,
  `progress.md`, and `factors.md`.
- In every `full-review` round, record whether the round produced fresh evidence
  and whether the current direction is becoming stale. In lightweight rounds,
  create `review.md` only when there is real review value; if it exists, it must
  be complete and aligned with `decision.md`.
- For phase gates, close decisions, and substantial `full-review` rounds, record
  the semantic review adapter in `Review Mode` and capture its findings in
  `review.md`.
- Record returned semantic findings under `Returned Review Findings` using the
  line format `- severity | category | location | claim | required_resolution`.
  Record accepted corrections separately; RDL may surface these records in gate
  details but must not infer that a semantic issue is truly resolved.
- When staleness appears, continue only with an explicit stall response, or
  change direction with prior directions checked.
- Index artifacts in `artifact-manifest.json`; do not copy project artifacts.
  Cite artifacts explicitly as `[artifact:ID]` in evidence and decisions.
- Keep markdown templates as the protocol surface.
- Keep guarded operation as thin transport only; RDL may record guard metadata
  but must not become a watchdog, experiment runner, git gate, or runtime
  supervisor.
- Avoid Humanize-style process captivity, broad shell validators, mandatory
  external review, and project-specific recovery rules.

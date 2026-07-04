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

## CLI

Run the Python module from a project repository:

```bash
PYTHONPATH=local/research-dev-loop python3 -m rdl start research mission.md --json
PYTHONPATH=local/research-dev-loop python3 -m rdl start build plan.md --json
PYTHONPATH=local/research-dev-loop python3 -m rdl status --json
PYTHONPATH=local/research-dev-loop python3 -m rdl handoff --json
PYTHONPATH=local/research-dev-loop python3 -m rdl memory --check --json
PYTHONPATH=local/research-dev-loop python3 -m rdl next --mode build --json
PYTHONPATH=local/research-dev-loop python3 -m rdl next --profile checkpoint --json
PYTHONPATH=local/research-dev-loop python3 -m rdl progress active --item parser --mode build --text "raw parser capability" --blocking no --trigger "sample coverage review" --json
PYTHONPATH=local/research-dev-loop python3 -m rdl factors set --section "Dataset or Workload" --value "current workload slice" --json
```

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
- At the start of a round, read `mission.md`, `progress.md`, `factors.md`,
  `decision-ledger.md`, and the previous round's decision/evidence records when
  they exist.
- Before running `rdl next`, update `progress.md` and `factors.md` when the
  round changes completed work, active claims or capabilities, blockers, open
  questions, directions tried, datasets, workloads, baselines, metrics,
  validators, prompts, backends, hardware, or nondeterminism.
- Use `rdl progress active|blocked|deferred|none` and
  `rdl factors set|note` to explicitly maintain top-level session memory
  without hand-editing Markdown tables.
- Use `rdl memory --check` when `doctor` reports weak session memory or a
  session has run for multiple rounds. Use `rdl memory --write` only to refresh
  deterministic managed summary blocks; still update active, blocked, deferred,
  and factor records manually when they require judgment.
- Keep deterministic gates limited to protocol, schema, local artifact
  integrity, and managed-summary facts. Do not encode semantic judgments such as
  whether evidence is decision-grade, an active item is truly stale, or a claim
  overreaches as ad hoc parser rules.
- In every `full-review` round, record whether the round produced fresh evidence
  and whether the current direction is becoming stale. In lightweight rounds,
  create `review.md` only when there is real review value; if it exists, it must
  be complete and aligned with `decision.md`.
- For phase gates, close decisions, and substantial `full-review` rounds, prefer
  an independent review adapter such as a subagent, `phase-review`, or a
  project-provided reviewer. Record the adapter in `Review Mode` and capture its
  findings in `review.md`; the caller should still interact through the normal
  `rdl review`, `rdl doctor`, `rdl next`, and `rdl close` flow.
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

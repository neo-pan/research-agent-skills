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
PYTHONPATH=local/research-dev-loop python3 -m rdl next --mode build --json
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
- Treat `.rdl/sessions/<session-id>/` as the recoverable state; do not depend on
  conversation memory for claims, evidence, open questions, or next steps.
- At the start of a round, read `mission.md`, `progress.md`, `factors.md`,
  `decision-ledger.md`, and the previous round's decision/evidence records when
  they exist.
- Before running `rdl next`, update `progress.md` and `factors.md` when the
  round changes completed work, active claims or capabilities, blockers, open
  questions, directions tried, datasets, workloads, baselines, metrics,
  validators, prompts, backends, hardware, or nondeterminism.
- In every review, record whether the round produced fresh evidence and whether
  the current direction is becoming stale.
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

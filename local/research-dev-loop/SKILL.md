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

Run the local script from a project repository:

```bash
local/research-dev-loop/scripts/rdl.sh start research mission.md
local/research-dev-loop/scripts/rdl.sh start build plan.md
local/research-dev-loop/scripts/rdl.sh status
```

## Requirements

The CLI requires Bash, standard POSIX-style shell tools, a SHA-256 command
(`sha256sum` or `shasum`), and a real JSON parser (`jq` or `python3`). RDL
returns `missing_json_tool` instead of validating JSON with text matching when
neither `jq` nor `python3` is available.

The manual profile should remain usable without hooks. Guarded operation, when
implemented, should call `rdl guard-stop` as thin transport and keep all RDL
logic inside the CLI.

## Python Refactor Checks

During the Python rewrite, use `./scripts/check-fast.sh` or
`./scripts/check.sh --fast` for the development inner loop. Fast mode runs
manifest/link checks, RDL Python tests, and repository prerequisite checks while
skipping the legacy Bash CLI compatibility suite under
`local/research-dev-loop/tests/*.sh`.

Use `./scripts/check.sh` or `./scripts/check.sh --full` before committing,
before removing Bash behavior, or when checking parity against the existing
`scripts/rdl.sh` implementation. Full mode retains the Bash compatibility suite
with per-test timeouts.

## Principles

- Keep one active RDL session per repository.
- Record evidence before advancing or closing decisions.
- Separate research claim closure from research capability closure.
- Index artifacts in `artifact-manifest.json`; do not copy project artifacts.
- Keep markdown templates as the protocol surface.
- Avoid Humanize-style process captivity, broad shell validators, git gates,
  mandatory external review, and project-specific recovery rules.

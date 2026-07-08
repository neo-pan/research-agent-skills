# Session Memory

Treat `.rdl/sessions/<session-id>/` as the recoverable state. Do not depend on
conversation memory for claims, evidence, open questions, or next steps.

Use `rdl handoff` or `rdl handoff --json` as the first read-only status surface
when taking over an existing long-running session. Use `--session-id` or
`--session-path` with read-only check surfaces when auditing a historical or
closed session instead of the active session.

At the start of a round, read `mission.md`, `progress.md`, `factors.md`,
`decision-ledger.md`, and the previous round's decision/evidence records when
they exist.

Before running `rdl next`, update `progress.md` and `factors.md` when the round
changes completed work, active claims or capabilities, blockers, open questions,
directions tried, datasets, workloads, baselines, metrics, validators, prompts,
backends, hardware, or nondeterminism.

When a broad mission needs decomposition, record the current mission slice in
`progress.md` and supporting context in `factors.md` or round records. Treat
slice quality, ordering, and completeness as semantic review concerns, not
deterministic gate rules.

Use `rdl progress active|blocked|deferred|none` and `rdl factors` to explicitly
maintain top-level session memory without hand-editing Markdown tables.

- `rdl progress active` defaults to the current session mode and
  `--blocking no`; pass `--mode` or `--blocking yes` only when they differ.
- `rdl factors --section ... --value ...` defaults to `set`; use
  `rdl factors note` to append a factor note instead of replacing the section.

Use `rdl memory --check` when `doctor` reports weak session memory or a session
has run for multiple rounds. Use `rdl memory --write` only to refresh
deterministic managed summary blocks; still update active, blocked, deferred,
and factor records manually when they require judgment.

Keep canonical RDL files single-writer. Subagents may inspect context and
produce findings, but the main agent or user must decide which judgment-heavy
changes to record in `review.md`, `decision.md`, `progress.md`, and
`factors.md`.

# Gates And Profiles

Keep one active RDL session per repository.

## Profiles

- Use `--profile full-review` for phase gates, go/no-go decisions, substantial
  review rounds, and closing rounds.
- Use `--profile checkpoint` for compact evidence and decision checkpoints.
- Use `--profile build-update` only in build mode for compact capability work
  updates.
- If no profile is supplied, RDL keeps the current profile and defaults new
  sessions to `full-review`.
- Lightweight profiles reduce round boilerplate; they do not remove the need
  for decision-grade evidence, `decision.md`, artifact discipline, or
  session-memory updates when state changes.

## Transitions

- Use `rdl next --mode build` or `rdl next --mode research` when the next round
  should change loop type. `Recommended next loop` records intent, but does not
  by itself switch mode.
- `rdl close` can infer `positive`, `negative`, or `inconclusive` from a
  current `Decision: close-*` record. Pass an explicit outcome only when the
  close decision is not already recorded or when checking a specific outcome.
- Successful `rdl next`, `rdl close`, and `rdl guard-stop` transitions write
  round-local `gate-report.json` and `gate.md` audit artifacts for the gate that
  allowed the transition. `rdl doctor` and `rdl handoff` remain read-only.

## Gate Boundary

Keep deterministic gates limited to protocol, schema, local artifact integrity,
state consistency, and managed-summary facts. Do not encode semantic judgments
such as whether evidence is decision-grade, an active item is truly stale, a
review trigger has semantically occurred, session memory faithfully represents
research state, or a claim overreaches as ad hoc parser rules.

Treat exact repeated next steps and missing recent artifact entries as semantic
review signals, not standalone deterministic gate warnings. A reviewer should
judge whether they are harmless continuation, stale direction reuse, or
insufficient evidence capture.

Keep guarded operation as thin transport only; RDL may record guard metadata but
must not become a watchdog, experiment runner, git gate, or runtime supervisor.
The manual profile should remain usable without hooks. Guarded operation, when
implemented, should call `rdl guard-stop` as thin transport and keep all RDL
logic inside the CLI.

Avoid Humanize-style process captivity, broad shell validators, mandatory
external review, and project-specific recovery rules.

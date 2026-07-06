# Research Development Loop Status

This local skill provides a lightweight file protocol and CLI for
evidence-backed research and research-engineering sessions. It is designed to
preserve mission, evidence, uncertainty, decisions, and handoff state under a
project-local `.rdl/` directory without becoming a runtime supervisor.

## Current Capabilities

- Mode transitions with `rdl next --mode research|build`.
- Round profiles: `full-review`, `checkpoint`, and `build-update`.
- Prompt carry-forward from top-level session memory and previous round records.
- Deterministic session summaries with `rdl summarize --check|--write`.
- Automatic deterministic managed summary refresh before successful `rdl next`
  and `rdl close` transitions.
- Session-memory diagnostics with `rdl memory --check|--write`.
- Session-memory quality warnings for duplicate open questions and malformed
  progress tables.
- Read-only takeover reports with `rdl handoff`.
- Unified gate reports consumed by `rdl doctor`, `rdl next`, `rdl close`,
  `rdl handoff`, and `rdl guard-stop`.
- Semantic review findings surfaced through the unified gate with a first
  read-only `review.md` adapter and clean RDL context pack.
- Agent-facing semantic review packs with `rdl review --pack --json`, including
  reviewer instructions, supplied RDL records, bounded prior-round context,
  cited artifact-producing round context, deterministic findings, artifact
  facts, finding schema, and review-only semantic signals.
- Round-local `gate-report.json` and `gate.md` audit artifacts written before
  successful `rdl next`, `rdl close`, and `rdl guard-stop` transitions.
- Read-only artifact gate checks for local artifact path reachability, byte
  size, sha256 metadata, and malformed optional integrity metadata when
  recorded in `artifact-manifest.json`.
- Explicit session-memory helpers with `rdl progress` and `rdl factors`.
- Common memory helper defaults: `rdl progress active` uses the current session
  mode and non-blocking status unless overridden; `rdl factors` defaults to
  `set` when a section and value are supplied.
- `rdl close` can infer the close outcome from a current `Decision: close-*`
  record.
- Explicit artifact citations with `[artifact:ID]` plus manifest validation.
- Optional `events.md` records for operational events that matter for recovery.
- A read-only external takeover gate with `scripts/rdl_dogfood_audit.sh`.

## Design Direction

RDL should use the default gate as the deep module for research-loop
trustworthiness. Deterministic checks should protect protocol, schema, managed
summaries, state consistency, and local artifact facts. Semantic checks should
protect research judgment: evidence sufficiency, overclaim risk, stale
directions, handoff faithfulness, and whether open or active items still
represent the true state.

Semantic review is agent-native first. `rdl review --pack --json` exposes the
clean context a reviewer agent needs without conversation history. The default
gate consumes completed `review.md` records after the main agent or user records
accepted findings. Later adapters may include an independent subagent,
`phase-review`, or a project-provided reviewer, but adapter mechanics should not
come before the agent-facing review contract. Reviewers must not directly mutate
canonical RDL files or advance the session.

Deterministic parser checks should stay limited to protocol, schema, managed
summary, state consistency, and local artifact facts. Signals such as repeated
next steps or missing recent artifact records are exposed to reviewer agents in
the review pack; they are not default gate warnings by themselves because their
research meaning requires judgment.

## Dogfood Takeover Workflow

Run the repository-level audit against an external project root containing an
active RDL session:

```bash
./scripts/rdl_dogfood_audit.sh <project-root>
```

If the audit fails, repair only the reported gaps:

```bash
rdl memory --write
rdl progress active|blocked|deferred|none ...
rdl factors set|note ...
rdl doctor --json
```

Then rerun the audit. A passing audit means a new agent can start from
`rdl handoff` and top-level session memory without scanning every round file
first.

## Deferred By Design

- Automatic synthesis of `factors.md`.
- Automatic inference of `Active`, `Blocked`, or `Deferred` progress rows.
- Broad rewriting of user-maintained session-memory files.
- RDL ownership of external review tools or project-specific reviewers.
  Semantic review belongs behind the gate adapter seam and must have a manual
  fallback.
- Automatic invocation of subagent or project-specific semantic reviewers.
- Legacy broad artifact-token citation detection.

These items remain deferred because they require judgment, can overwrite user
intent, or would make RDL heavier than a recoverable evidence protocol.

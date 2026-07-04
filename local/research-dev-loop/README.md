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
- Read-only artifact gate checks for local artifact path reachability, byte
  size, sha256 metadata, and malformed optional integrity metadata when
  recorded in `artifact-manifest.json`.
- Explicit session-memory helpers with `rdl progress` and `rdl factors`.
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

Semantic review should sit behind a gate adapter seam, not behind extra
user-facing ceremony. Adapters may include an independent subagent, manual
review, `phase-review`, or a project-provided reviewer. Subagent adapters should
receive a clean RDL context pack with session records, relevant artifacts,
deterministic gate findings, and verification evidence, rather than inheriting
the main conversation history. Adapter findings should be recorded through the
normal review and gate-report surfaces; adapters must not directly mutate
canonical RDL files or advance the session.

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
- Legacy broad artifact-token citation detection.

These items remain deferred because they require judgment, can overwrite user
intent, or would make RDL heavier than a recoverable evidence protocol.

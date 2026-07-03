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
- Session-memory diagnostics with `rdl memory --check|--write`.
- Read-only takeover reports with `rdl handoff`.
- Explicit session-memory helpers with `rdl progress` and `rdl factors`.
- Explicit artifact citations with `[artifact:ID]` plus manifest validation.
- Optional `events.md` records for operational events that matter for recovery.
- A read-only external takeover gate with `scripts/rdl_dogfood_audit.sh`.

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
- External review automation beyond the local CLI workflow.
- Legacy broad artifact-token citation detection.

These items remain deferred because they require judgment, can overwrite user
intent, or would make RDL heavier than a recoverable evidence protocol.

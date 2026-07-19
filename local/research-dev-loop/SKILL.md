---
name: research-dev-loop
description: Durable RDL sessions for multi-round research or build work that must survive handoff or bind material decisions to evidence.
---

# Research Development Loop

Use RDL as a write-through evidence record, not a project supervisor. Resolve this loaded skill's absolute `bin/rdl` path once as `RDL`; do not discover it by bare command name. The CLI owns normalized state and renders the files under `.rdl/`; treat those files as inspectable views and submit changes with `"$RDL" apply`.

## Run the loop

1. Start with structured mission JSON, or take over an existing session with `"$RDL" handoff`. Completion: the current action, blockers, and smallest evidence step are explicit.
2. Execute that evidence step. Completion: retain the raw result, uncertainty, and any artifact or verifier receipt.
3. Write-through with one `"$RDL" apply --input <path|->` before starting more external work. Completion: a successful receipt returns durable IDs and a new state version.
4. Branch on the receipt:
   - Continue evidence work while `transition_readiness` is not `ready`.
   - When `review_required` is true, obtain a fresh material review and apply its result. Read [SEMANTIC_REVIEW.md](SEMANTIC_REVIEW.md) for this branch.
   - Run `"$RDL" next` or `"$RDL" close` only with the receipt's current version and only when readiness is `ready`.
5. After transition, use the returned state as the next round or terminal completion criterion.

Use `"$RDL" doctor` when handoff or a command reports abnormal state. Use `--session-id` for historical state or a lost close response. For request schemas and typed errors, read [CLI.md](CLI.md).

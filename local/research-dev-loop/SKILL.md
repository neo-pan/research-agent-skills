---
name: research-dev-loop
description: Durable RDL sessions for multi-round research or build work that must survive handoff or bind material decisions to evidence.
---

# Research Development Loop

Use RDL as write-through evidence, not a supervisor. Resolve this skill's absolute `bin/rdl` as `RDL`, never by bare command. The CLI owns state; change `.rdl/` only through `"$RDL" apply`.

## Run the loop

1. Start from mission JSON or `"$RDL" handoff`; any `current_action` is the accepted takeover contract.
2. Execute its smallest evidence step; retain results, uncertainty, and receipts. Do not precompute file sizes or checksums for artifact entries: `apply` records size and SHA-256. Run a verifier only when it tests the substantive claim; checksum-only commands such as `sha256sum` are redundant.
3. Before more external work, `apply`; retain the returned IDs and version.
4. Branch on the receipt:
   - Continue evidence while readiness is not `ready`.
   - If `review_required`, follow [SEMANTIC_REVIEW.md](SEMANTIC_REVIEW.md) and apply the result.
   - Run `next` or `close` only with the current version when ready.
5. Continue from the returned round or terminal state. Before `next`, persist the next action and remaining phases in mission, unfinished progress, or `decision.next_step`.

For builds: failing baseline → `apply` → implement/verify → `apply`. Freeze receipts; prefer snapshots and short sessions. Reconcile changed relevant `live` artifacts by retirement or same-apply snapshot supersession. Never edit `.rdl` or infer a result from drift. See [OPERATIONS.md](OPERATIONS.md).

Use `doctor` for abnormal state and `--session-id` for history or lost close responses. See [CLI.md](CLI.md) for schemas and errors.

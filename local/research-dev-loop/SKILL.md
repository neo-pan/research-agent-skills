---
name: research-dev-loop
description: Operate an existing RDL session, or start one only when explicitly requested for durable multi-round work requiring handoff or evidence-bound decisions. Bounded reviews stay outside RDL.
---

# Research Development Loop

Use RDL as write-through evidence. Rounds are material decision boundaries; routine applies stay in-round without review. Resolve this skill's absolute `bin/rdl` as `RDL`; never use PATH. Mutate `.rdl` through `"$RDL" apply` only.

## Gate

- Inspect with `handoff`; use `doctor` only for abnormal state. Do not run semantic review, `apply`, `next`, or `close` unless the user asks.
- Resume only the governing session. Start one only when explicitly requested for durable multi-round, handoff, or evidence-bound work.
- Bounded reviews stay outside RDL; loading grants no mutation authority.

## Run the loop

1. Start an authorized session from mission JSON; otherwise `handoff`. `current_action` is the takeover contract.
2. Execute its smallest evidence step and retain receipts. Do not precompute file sizes or checksums for artifact entries: `apply` records them. Verify substantive claims only; checksum-only commands such as `sha256sum` are redundant.
3. At checkpoints or before external work, `apply`; retain IDs and version. See [OPERATIONS.md](OPERATIONS.md).
4. Continue until ready. On `review_required`, follow [SEMANTIC_REVIEW.md](SEMANTIC_REVIEW.md) and apply the result. Run `next` or `close` only with the current ready version.
5. Before `next`, persist the executable action, completion condition, remaining phases, and retry unlock in `decision.next_step`.

For builds: failing baseline → `apply` → implement/verify → `apply`. Freeze receipts. Reconcile changed `live` artifacts by retirement or same-apply snapshot supersession; never infer from drift. See [OPERATIONS.md](OPERATIONS.md).

Use `--session-id` for history or lost closes. See [CLI.md](CLI.md).

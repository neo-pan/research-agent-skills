---
name: research-dev-loop
description: Operate RDL sessions, or start one only when explicitly requested for durable multi-round handoff or evidence-bound decisions. Bounded reviews stay outside RDL.
---

# Research Development Loop

Use RDL as evidence. Rounds are material decisions; routine applies stay in-round. Resolve this skill's absolute `bin/rdl` as `RDL`; never use PATH. Mutate `.rdl` through `"$RDL" apply` only. See [CLI.md](CLI.md).

## Gate

- Inspect with `handoff`; reserve `doctor` for abnormal state. Do not run semantic review, `apply`, `next`, or `close` unless the user asks.
- Resume only the governing session. Start one only when explicitly requested for durable multi-round, handoff, or evidence-bound work.
- If a mission needs plan or phase review, obtain its PASS before `start`; replace materially changed missions.
- Bounded reviews stay outside RDL; loading grants no mutation authority.

## Run the loop

1. Start an authorized mission; otherwise `handoff`. `current_action` is the takeover contract.
2. Execute its smallest evidence step. Do not precompute file sizes or checksums for artifact entries: `apply` records them. Verify substantive claims; checksum-only commands such as `sha256sum` are redundant.
3. At checkpoints or before external work, `apply`; retain its receipt. See [OPERATIONS.md](OPERATIONS.md).
4. On `review_required`, follow [SEMANTIC_REVIEW.md](SEMANTIC_REVIEW.md) and apply the result. Transition only with the ready version.
5. Before `next`, persist the executable action, completion condition, remaining phases, and retry unlock in `decision.next_step`.
6. Before a non-abandoned close, resolve each `active` progress item to `completed`, `deferred`, or `open_question`.

For builds: failing baseline → `apply` → implement/verify → `apply`. Freeze receipts. Retire changed `live` artifacts or supersede them with same-apply snapshots. See [OPERATIONS.md](OPERATIONS.md).

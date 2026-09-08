---
name: research-dev-loop
description: Operate RDL sessions, or start one only when explicitly requested for durable multi-round handoff or evidence-bound decisions. Bounded reviews stay outside RDL.
---

An apply that records a directional decision, a close, or a review trigger requires review; other applies stay in-round. Resolve this skill's absolute `bin/rdl` as `RDL`; submit research changes through `"$RDL" apply`. Use lifecycle commands for transitions; see [CLI.md](CLI.md).

## Gate

- Inspect with `handoff`; use `doctor` for abnormal state.
- Do not run semantic review, `apply`, `next`, or `close` unless the user asks. Authorization to operate this session covers bounded checkpoints and transitions. After compaction, recover with `handoff` and continue under retained authorization; ask only if authorization cannot be recovered or scope exceeds it. State alone grants no authority.
- Resume the governing session; start one only when explicitly requested for durable handoff or evidence-bound work.
- If a mission needs plan or phase review, obtain its PASS before `start`; replace missions only when `objective` or `success_criteria` change.
- Mission items are one sentence each; omit protocol guarantees already enforced by RDL.
- Freeze commit, diff, and file identities as round-1 evidence. Changed code is new evidence, not a new mission.
- Bounded reviews stay outside RDL; loading grants no authority.

## Run the loop

1. Start an authorized mission; otherwise use `handoff.current_action` as the takeover contract.
2. Read `"$RDL" schema` before composing a delta. Execute the smallest evidence step. Do not precompute file sizes or checksums for artifact entries: `apply` records them. Verify claims; checksum-only commands such as `sha256sum` are redundant.
3. At checkpoints or before external work, `apply`; retain receipt. For external work use `intent apply → execute → result apply → review/transition`; see [OPERATIONS.md](OPERATIONS.md).
4. On `review_required`, follow [SEMANTIC_REVIEW.md](SEMANTIC_REVIEW.md) and apply the result. Transition only with the ready version.
5. Before `next`, persist the action, completion condition, remaining phases, and retry unlock in `decision.next_step`.
6. Before a non-abandoned close, resolve each `active` progress item to `completed`, `deferred`, or `open_question`.

For builds: failing baseline → `apply` → implement/verify → `apply`. An artifact records the bytes frozen at registration; when those bytes change, register the new file as a new artifact and cite it from new evidence.

---
name: research-dev-loop
description: Operate RDL sessions, or start one only when explicitly requested for durable multi-round handoff or evidence-bound decisions. Bounded reviews stay outside RDL.
---

An apply that records a directional decision, a close, or a review trigger requires review; other applies stay in-round. Resolve this skill's absolute `bin/rdl` as `RDL`; mutate only through `"$RDL" apply`. See [CLI.md](CLI.md).

## Gate

- Inspect with `handoff`; use `doctor` for abnormal state. Do not run semantic review, `apply`, `next`, or `close` unless the user asks.
- Resume the governing session; start one only when explicitly requested for durable handoff or evidence-bound work.
- If a mission needs plan or phase review, obtain its PASS before `start`; replace missions only when `objective` or `success_criteria` change.
- Mission items are one sentence each. Do not restate RDL's own guarantees — immutability, append-only history, review gating, and successor discipline are enforced by the protocol, not by mission text.
- Freeze commit, diff, and file identities as round-1 baseline evidence, never as mission text. A changed code baseline is new evidence in the same session, not a new mission.
- Bounded reviews stay outside RDL; loading grants no authority.

## Run the loop

1. Start an authorized mission; otherwise use `handoff.current_action` as the takeover contract.
2. Work at the smallest existing seam; execute its smallest evidence step. Do not precompute file sizes or checksums for artifact entries: `apply` records them. Verify claims; checksum-only commands such as `sha256sum` are redundant.
3. At checkpoints or before external work, `apply`; retain receipt. See [OPERATIONS.md](OPERATIONS.md).
4. On `review_required`, follow [SEMANTIC_REVIEW.md](SEMANTIC_REVIEW.md) and apply the result. Transition only with the ready version.
5. Before `next`, persist the action, completion condition, remaining phases, and retry unlock in `decision.next_step`.
6. Before a non-abandoned close, resolve each `active` progress item to `completed`, `deferred`, or `open_question`.

For builds: failing baseline → `apply` → implement/verify → `apply`. An artifact records the bytes frozen at registration; when those bytes change, register the new file as a new artifact and cite it from new evidence.

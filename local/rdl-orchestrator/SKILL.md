---
name: rdl-orchestrator
description: Drive an RDL session to a terminal result.
---

# RDL Orchestrator

Drive one existing session until terminal. Explicitly load `research-dev-loop` as this workflow's dependency; resolve its absolute `bin/rdl` as `RDL`. If unavailable, report a dependency blocker; never guess a sibling path or use bare PATH. RDL state grants no external authority.

## Take over once

Run `"$RDL" handoff` once, again after context loss or takeover; use `"$RDL" doctor` only for abnormal state. Recover the action, blocker, and smallest evidence step.

## Terminal loop

1. Execute the smallest evidence step. Completion: raw results, uncertainty, and artifacts are available.
2. Write-through with `"$RDL" apply` before more external work; routine receipts stay in-round with no reviewer.
3. Before a material build's final decision, follow the project-review reference in the loaded RDL skill's `OPERATIONS.md`; apply its receipt.
4. If semantic review is required, follow that skill's `SEMANTIC_REVIEW.md`, adjudicate and apply findings; repeat valid reviews only for a changed digest.
5. When ready, run `"$RDL" next` or `"$RDL" close`; otherwise continue evidence work in-round.

Stop only after a closed/abandoned receipt, an explicit user pause, or a typed external blocker whose required input is write-through and for which no safe work remains.

Before external actions, incorporate user corrections using `OPERATIONS.md`'s "User steering" rules. Answer side questions without losing the active mission.

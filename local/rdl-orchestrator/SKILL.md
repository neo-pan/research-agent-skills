---
name: rdl-orchestrator
description: Drive an RDL session to a terminal result.
---

# RDL Orchestrator

Drive one existing session until it is terminal. First load and locate `research-dev-loop`, then resolve that skill's absolute `bin/rdl` path as `RDL`. Stop with a dependency blocker if the skill cannot be located; do not guess a sibling path or use a bare PATH command. RDL records preserve state and evidence; they do not grant authority for external actions.

## Take over once

Run `"$RDL" handoff` once; repeat only after context loss or takeover. Use `"$RDL" doctor` only for abnormal state. Completion: recover the current action, blocker, and smallest evidence step.

## Terminal loop

1. Execute the smallest evidence step. Completion: raw results, uncertainty, and artifacts are available.
2. Write-through with `"$RDL" apply` before more external work; routine receipts stay in-round with no reviewer.
3. Before a material build's final decision, follow the project-review reference and apply its current receipt.
4. If semantic review is required, follow the material reference, adjudicate findings, and apply the result; repeat only for a changed digest.
5. When ready, run `"$RDL" next` or `"$RDL" close`; otherwise continue evidence work in-round.

Stop only after a closed/abandoned receipt, an explicit user pause, or a typed external blocker whose required input is write-through and for which no safe work remains.

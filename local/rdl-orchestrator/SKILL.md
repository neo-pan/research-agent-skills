---
name: rdl-orchestrator
description: Drive an RDL session to a terminal result.
disable-model-invocation: true
---

# RDL Orchestrator

Drive one existing session until it is terminal. RDL records preserve state and evidence; they do not grant authority for external actions.

## Take over once

Run `rdl handoff`. Use `rdl doctor` only when handoff reports abnormal state. Completion: recover the current action, blocker, and smallest evidence step.

## Terminal loop

1. Execute the smallest evidence step. Completion: raw results, uncertainty, and artifacts are available.
2. Write-through with `rdl apply` before more external work. Completion: a successful receipt returns the new version.
3. If the receipt requires material review, follow the material reference from `research-dev-loop`, accept or reject each finding, and apply the result. Completion: the current action and subject digest are matched.
4. If review remains required, repeat it for the current digest. Otherwise, when readiness is not `ready`, repeat from evidence work in the same round.
5. If readiness is `ready`, run `rdl next` or `rdl close` with the current version, then continue from the returned state.

Stop only after a closed/abandoned receipt, an explicit user pause, or a typed external blocker whose required input is write-through and for which no safe work remains.

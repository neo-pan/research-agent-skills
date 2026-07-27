# RDL Operations

## Executable next actions

Before `next`, make `decision.next_step` state the smallest evidence action, its task-specific completion condition, the expected later transition when known, and remaining phases. Multi-round requirements belong in mission, unfinished progress, or that instruction.

## Receipt-first apply

Freeze the command, exit, decisive output, environment boundary, and stable project-relative snapshot before composing apply JSON. Replace the example versions, paths, refs, and digest with current values.

Research — register a frozen receipt and its bounded claim:

```json
{"expected_state_version":4,"risk":"routine","artifacts":{"probe":{"kind":"receipt","path":"evidence/probe.json","description":"frozen probe receipt","stability":"snapshot"}},"evidence":{"probe-result":{"claim":"the bounded probe completed","summary":"the receipt records the command and result","bearing":"supports","strength":"moderate","artifact_refs":["probe"],"uncertainty":"fixture-scoped"}}}
```

Build — write through passing verification and the next action:

```json
{"expected_state_version":5,"risk":"material","artifacts":{"verification":{"kind":"test-receipt","path":"evidence/verification.json","description":"post-change verification","stability":"snapshot"}},"evidence":{"verified":{"claim":"the bounded change passes verification","summary":"focused and regression checks passed","bearing":"supports","strength":"strong","artifact_refs":["verification"],"uncertainty":"local environment only"}},"decision":{"kind":"accept","subject":"advance to the next bounded phase","evidence_refs":["verified"],"uncertainty":"broader environments remain untested","remaining_unknowns":["broader portability"],"next_step":"Run the portability matrix; complete when its frozen receipt passes, then record a close decision.","recommended_transition":"next"}}
```

Review result — apply the exact reviewed action and digest:

```json
{"expected_state_version":6,"risk":"routine","review_result":{"action":"next","subject_digest":"0000000000000000000000000000000000000000000000000000000000000000","adapter":"independent-reviewer","verdict":"pass","findings":[]}}
```

The loop remains:

```text
research: artifact receipt + evidence + uncertainty -> apply
build: failing receipt -> apply -> implement/verify -> passing receipt + decision -> apply
review: exact action/digest/adapter + adjudicated findings -> apply review_result
```

Use `"$RDL" apply --input <file>` for each payload. Do not copy placeholder values into a session.

## Compact handoff

Handoff normally returns the complete inline projection. Above 24 KiB it returns a bounded `compact_manifest` with the immutable generation's authoritative `state.json`, state digest, required JSON sections, omitted inline sections, and full-projection byte accounting. Read those sections before acting. The 20 KiB target is diagnostic only. Semantic review remains complete and all-inline: 32 KiB is a diagnostic soft budget and 48 KiB is the fail-closed hard budget.

## Terminal audit

After close, retain one compact audit covering final handoff and doctor, exact close replay, current-version terminal mutation rejection, stale-request rejection, and unchanged pointer, generation set, state version, and recursive store digest. For every probe, record the command/arguments, exit code, and decisive typed result. For the store digest, also record the exact algorithm or command, digest root, and exclusions so another agent can reproduce it.

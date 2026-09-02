# RDL Operations

## Executable next actions

Before `next`, make `decision.next_step` state the smallest evidence action, its task-specific completion condition, expected evidence, remaining phases, and—when the action is expensive—the evidence or hypothesis change that unlocks a rerun. Multi-round requirements belong in mission, unfinished progress, or that instruction.

## Checkpoints and expensive actions

Checkpoint after an expensive external action, before changing hypothesis/phase/mutation scope, after transition-relevant evidence, before waiting or pausing, and after a build's failing baseline, passing verification, or project-review receipt. Ordinary navigation and short helper commands inside one bounded action need no checkpoint.

Use the cheapest gate that can falsify the current change: focused red → local repair → focused green → affected regression checks. Run a broader suite when the changed interface or project contract requires it. Freeze each receipt with its executed scope, result, and untested boundary.

Work at the smallest existing seam and require evidence sufficient for the bounded claim; record unrelated uncertainty as an untested boundary. Add abstractions, compatibility or defensive branches, and general-readiness gates only for a supported contract or observed failure. Keep correctness, provenance, and fail-closed protocol checks authoritative.

For large-context LLM calls, hardware experiments, long profiling, or broad benchmarks, add one real confirmation after deterministic green. Before another real attempt, apply the prior result and identify new evidence, a materially changed hypothesis/input/implementation, a low-cost check proving that change, or a directly relevant environment change. Do not set a global retry count.

## Material build project review

Before a build closes a code, config, or script claim—or when the mission or review trigger requires it—run the project's single configured read-only reviewer on the original boundary, final diff, verification receipts, deferrals, and out-of-scope work. Prefer a committed candidate and freeze the reviewed diff as the ordered `git diff <base-commit> <result-commit> -- <reviewed-paths>` comparison. If pre-commit review is necessary, freeze the base HEAD, reviewed path scope, and the Git blob object ID produced by piping the exact `git diff --binary --full-index --no-ext-diff HEAD -- <paths>` bytes to `git hash-object --stdin`; bind that blob ID to the exact diff byte stream, and require relevant untracked files to enter that Git diff first or the review remains incomplete. Do not invent an RDL-specific diff digest. Freeze the adapter, boundary, Git diff identity, verification refs, verdict, findings, and deferrals as a snapshot artifact and apply evidence citing it. Any relevant code or verification change makes that receipt stale: fix, verify, regenerate the Git identity, review again, and apply the replacement before semantic close review. Research and no-code material claims do not trigger this gate automatically. If no required adapter is available, record a blocker; never synthesize a pass.

## Receipt-first apply

Freeze the command, exit, decisive output, environment boundary, and stable project-relative snapshot before composing apply JSON. Replace the example versions, paths, refs, and digest with current values.

Reuse a durable `A` ID when later evidence cites the same registered artifact identity. If later work adds interpretation or bounded excerpts, freeze that material as its own receipt and cite both IDs from the new evidence; do not re-register the original path. Register a new artifact only for new bytes or a new path identity.

Research — register a frozen receipt and its bounded claim:

```json
{"expected_state_version":4,"artifacts":{"probe":{"kind":"receipt","path":"evidence/probe.json","description":"frozen probe receipt"}},"evidence":{"probe-result":{"claim":"the bounded probe completed","summary":"the receipt records the command and result","bearing":"supports","strength":"moderate","artifact_refs":["probe"],"uncertainty":"fixture-scoped"}}}
```

When a review trigger depends on decisive content, put a bounded summary in the existing
evidence `summary` and reference the raw receipt artifact from `artifact_refs`. This is a
caller workflow convention; RDL does not parse the receipt or judge semantic sufficiency.

Build — write through passing verification and the next action:

```json
{"expected_state_version":5,"artifacts":{"verification":{"kind":"receipt","path":"evidence/verification.json","description":"post-change verification"}},"evidence":{"verified":{"claim":"the bounded change passes verification","summary":"focused and regression checks passed","bearing":"supports","strength":"strong","artifact_refs":["verification"],"uncertainty":"local environment only"}},"decision":{"kind":"accept","subject":"advance to the next bounded phase","evidence_refs":["verified"],"uncertainty":"broader environments remain untested","remaining_unknowns":["broader portability"],"next_step":"Run the portability matrix; complete when its frozen receipt passes, then record a close decision.","recommended_transition":"next"}}
```

Review result — apply the exact reviewed action and digest:

```json
{"expected_state_version":6,"review_result":{"action":"next","subject_digest":"0000000000000000000000000000000000000000000000000000000000000000","adapter":"independent-reviewer","verdict":"pass","findings":[]}}
```

The loop remains:

```text
research: artifact receipt + evidence + uncertainty -> apply
build: failing receipt -> apply -> implement/verify -> passing receipt + decision -> apply
review: exact action/digest/adapter + adjudicated findings -> apply review_result
```

For an external action, keep the sequence `intent apply -> execute -> result apply`.
Transport retries may share one result receipt only when canonical input, policy, source
identity, and budget are unchanged; otherwise the caller records a new arm or confounder.

Use `"$RDL" apply --input <file>` for each payload. Do not copy placeholder values into a session.

## Compact handoff

Handoff may return a bounded `compact_manifest` with the immutable generation's authoritative `state.json`, state digest, required JSON sections, omitted inline sections, and full-projection accounting. Read the returned sections before acting. This does not provide compact review recovery. Semantic review remains complete and all-inline; if its internal hard limit is exceeded, inspect the returned size/section details and use the existing round/session recovery path.

When an active round has a `next` or `close` decision, ordinary apply and handoff receipts may include a compact `review_budget` estimate. A crossing adds a warning; formal `review` remains fail-closed when its internal limit is exceeded. Detailed section accounting is available from `doctor --diagnostics`.

Terminal handoff has no `current_action`. Its full-inline `terminal_summary` reports outcome, the review binding that authorized that outcome, unfinished progress, and labels the old next-step text as `pre_close_instruction`. A compact manifest keeps only fixed facts, status counts, and canonical section pointers; arbitrary text and lists remain in `state.json`/`final-report.md`. Abandoned sessions have no final review binding.

# RDL Operations

## Executable next actions

Before `next`, make `decision.next_step` state the smallest evidence action, its task-specific completion condition, expected evidence, remaining phases, and—when the action is expensive—the evidence or hypothesis change that unlocks a rerun. Multi-round requirements belong in mission, unfinished progress, or that instruction.

## Checkpoints and expensive actions

Checkpoint after an expensive external action, before changing hypothesis/phase/mutation scope, after transition-relevant evidence, before waiting or pausing, and after a build's failing baseline, passing verification, or project-review receipt. Ordinary navigation and short helper commands inside one bounded action need no checkpoint.

For large-context LLM calls, hardware experiments, long profiling, or broad benchmarks use: deterministic red → local repair → deterministic green → one real confirmation. Before another real attempt, apply the prior result and identify new evidence, a materially changed hypothesis/input/implementation, a low-cost check proving that change, or a directly relevant environment change. Do not set a global retry count.

## Material build project review

Before a build closes a code, config, or script claim—or when the mission or review trigger requires it—run the project's single configured read-only reviewer on the original boundary, final diff, verification receipts, deferrals, and out-of-scope work. Freeze its adapter, boundary, diff identity, verification refs, verdict, findings, and deferrals as a snapshot artifact and apply evidence citing it. Any relevant code or verification change makes that receipt stale: fix, verify, regenerate the diff, review again, and apply the replacement before semantic close review. Research and no-code material claims do not trigger this gate automatically. If no required adapter is available, record a blocker; never synthesize a pass.

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

When an active round has a `next` or `close` decision, ordinary apply and handoff receipts include the same compact `review_budget` estimate. A soft or hard crossing adds `review_pack_soft_budget_exceeded` or `review_pack_over_budget` to `warnings`; these are early signals, while formal `review` retains the 48 KiB fail-closed gate. When transition readiness is `needs_review`, detailed section accounting is available from `doctor --diagnostics`.

Terminal handoff has no `current_action`. Its full-inline `terminal_summary` reports outcome, the review binding that authorized that outcome, unfinished progress, and labels the old next-step text as `pre_close_instruction`. A compact manifest keeps only fixed facts, status counts, and canonical section pointers; arbitrary text and lists remain in `state.json`/`final-report.md`. Abandoned sessions have no final review binding.

## Terminal audit

Run `scripts/rdl_dogfood_audit.sh [--session-id ID] --subagent-calls N [--json-output PATH] PROJECT_ROOT`. `N` is the caller-reported total for the session; the audit validates only that it is a non-negative integer and never infers calls from RDL state or transcripts. Active sessions receive handoff/doctor diagnostics only. Terminal sessions also cover exact close replay, current-version terminal mutation rejection, stale-request rejection, and unchanged pointer, generation set, state version, and recursive store digest. Every probe records argv/input, exit code, and decisive typed result; the receipt also copies `doctor --diagnostics` projection accounting without interpretation. The digest records its algorithm, root, and exclusions. JSON output must remain outside `.rdl`, and the audit must not write RDL state. Reviewers remain responsible for judging whether reported calls and evidence are sufficient.

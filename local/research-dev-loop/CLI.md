# RDL CLI

Resolve this loaded skill's absolute `bin/rdl` as `RDL` and invoke `"$RDL"`; a bare `rdl` exists only in explicitly configured human shells. The launcher needs Python 3.9+ on Linux/WSL and treats the caller's working directory as project root. Each command emits one JSON object: exit `0` success, `2` a typed blocker, `1` invalid input or damaged local state. Bootstrap failures use stderr and exit `1`; `--help` stays human-readable text.

```text
"$RDL" schema
"$RDL" start --input <path|-> [--session-id ID]
"$RDL" handoff [--session-id ID]
"$RDL" apply --input <path|-> [--session-id ID]
"$RDL" review --for next|close [--session-id ID]
"$RDL" next --expected-state-version N [--session-id ID]
"$RDL" close --expected-state-version N --outcome positive|negative|inconclusive|abandoned [--reason TEXT] [--session-id ID]
"$RDL" doctor [--session-id ID] [--diagnostics]
```

`schema` needs no session, mutates nothing, and prints every closed value set, the rule that decides when review is required, and the mission soft budget. Read it rather than guessing an enum; the prose here summarizes it and is not the source.

Start input has `mode: research|build` and a mission with `objective`, non-empty `scope` and `success_criteria`, plus optional `out_of_scope`, `invariants`, and `abort_criteria`. Keep mission items to one sentence each and out of RDL's own guarantees; see [SKILL.md](SKILL.md). `start` warns past the mission soft budget, because every review resends it.

An ApplyDelta requires `expected_state_version`. Optional: append-only `artifacts` and `evidence` maps; a whole-value `progress_updates` map where map-level `null` deletes; a current-round `decision` replacement; one `review_trigger`; one `review_result`.

Artifacts carry a closed `kind`, project-relative `path`, and `description`; `apply` records size and sha256 for the bytes present at registration. Evidence carries `claim`, `summary`, `bearing`, `strength`, artifact refs, and uncertainty. A decision carries `kind`, `subject`, evidence refs, uncertainty, remaining unknowns, next step, `recommended_transition`, optional next mode, and a scientific close outcome when closing. Delta-local refs resolve before durable `A/E/EV/R` IDs are assigned.

`handoff` returns `current_action` after `next`, `terminal_summary` after close, or a bounded `compact_manifest` when oversized; see [OPERATIONS.md](OPERATIONS.md). With no active session and no explicit `--session-id` it answers `{"status":"ok","session_status":"none"}` at exit `0` — absence is a fact, not a blocker. Every other command still blocks with `no_active_session`.

`close --reason` is required for `abandoned` and ignored for every other outcome.

All existing-session mutations require the current version. An exact immediate retry returns the previous receipt; a different or older request returns `state_version_conflict`. Use an explicit session ID to retry a lost close response.

Rejects are atomic: an `unknown_reference` or unreadable artifact path leaves state unchanged.

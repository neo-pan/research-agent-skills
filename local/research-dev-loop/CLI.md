# RDL CLI

Resolve this loaded skill's absolute `bin/rdl` path as `RDL`, then invoke `"$RDL"`; the optional bare `rdl` adapter is for explicitly configured human shells. The launcher requires Python 3.9+ on Linux/WSL and preserves the caller's working directory as project root. After launcher bootstrap, commands emit one JSON object: exit `0` means success, `2` a typed blocker, and `1` invalid input or damaged local state. Bootstrap failures use stderr and exit `1`; `--help` remains human-readable text.

```text
"$RDL" start --input <path|-> [--session-id ID]
"$RDL" handoff [--session-id ID]
"$RDL" apply --input <path|-> [--session-id ID]
"$RDL" review --for next|close [--session-id ID]
"$RDL" next --expected-state-version N [--session-id ID]
"$RDL" close --expected-state-version N --outcome positive|negative|inconclusive|abandoned [--reason TEXT] [--session-id ID]
"$RDL" doctor [--session-id ID] [--diagnostics]
```

Start input contains `mode: research|build` and a mission with `objective`, non-empty `scope` and `success_criteria`, plus optional `out_of_scope`, `invariants`, and `abort_criteria` arrays.

An ApplyDelta requires `expected_state_version` and `risk: routine|material`. Optional fields are:

- append-only `artifacts`, `evidence`, and `events` maps;
- whole-value `progress_updates` and `factor_updates` maps, where map-level `null` deletes;
- current-round `interpretation` and `decision` replacements;
- one `review_trigger` and one `review_result`.

Artifact entries contain `kind`, project-relative `path`, `description`, `stability: snapshot|live`, and an optional compact verifier receipt. Evidence contains `claim`, `summary`, `bearing`, `strength`, artifact refs, and uncertainty. Delta-local refs resolve before durable `A/E/EV/R` IDs are assigned.

A decision contains `kind`, `subject`, evidence refs, uncertainty, remaining unknowns, next step, `recommended_transition: next|close|none`, optional next mode, and a scientific close outcome when closing.

All existing-session mutations require the current version. An exact immediate retry returns the previous receipt; a different or older request returns `state_version_conflict`. Use an explicit session ID to retry a lost close response.

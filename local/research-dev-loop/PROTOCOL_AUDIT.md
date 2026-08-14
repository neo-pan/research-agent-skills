# RDL Protocol Audit

This is a conditional regression gate for RDL itself, not evidence that a project's scientific result is correct.

Run it only when the work changes RDL protocol, storage, transitions, projections, or the audit; when the mission explicitly requires protocol acceptance; or when `handoff`, `doctor`, terminal replay, or store consistency is anomalous. Ordinary research and development sessions end after their current semantic close review, required project verification/review, and persisted close receipt.

Resolve this skill's absolute `bin/rdl-audit` as `RDL_AUDIT`, then run:

```text
"$RDL_AUDIT" [--session-id ID] --subagent-calls N [--json-output PATH] PROJECT_ROOT
```

`N` is caller-reported metadata; the audit validates its shape and never infers calls from state or transcripts. Active sessions receive handoff and doctor diagnostics. Terminal sessions additionally cover exact close replay, current-version terminal mutation rejection, stale-request rejection, and unchanged pointer, generations, state version, and recursive store digest.

Write JSON output outside `.rdl`. Treat a failed audit as a protocol or state-integrity finding to diagnose; do not rerun unchanged to obtain a pass. The audit does not replace scientific correctness, performance, provenance, cleanup, or claim-scope evidence.

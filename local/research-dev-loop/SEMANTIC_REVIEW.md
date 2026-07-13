# Semantic Review

Use `rdl review --pack --for next|close|doctor --json` to produce an
action-aware clean context pack for a reviewer. Use the generic
`rdl review --pack --json` form only when no intended action is known or for a
backward-compatible caller. A close pack requires a current `Decision: close-*`
record so the reviewer assesses a specific proposed outcome.
The pack includes RDL records, artifact manifest facts, deterministic findings,
reviewer instructions, a finding schema, and semantic signals that require
judgment. It also includes a `subject_digest` that binds the review to the
action and supplied subject. It must not create or modify `review.md`.

Record both `Review Subject Action` and `Review Subject Digest` from the pack
in `review.md`. New reviews should bind both fields exactly. Reviews created
before subject binding remain compatible when both fields are absent.

The digest covers the action, session identity, mode/profile, mission and
session memory, current subject records, bounded prior context, close report,
canonical artifact manifest facts, stable deterministic artifact/evidence
findings, and agent review signals. It excludes the current `review.md` and
RDL-generated progress or ledger summary blocks. Reordering JSON object keys
does not change the digest; changing evidence, decisions, human-maintained
memory, close scope, or artifact facts does.

CLI-generated close-transition ledger blocks are deterministic bookkeeping and
are excluded from the subject just like generated summary blocks. New blocks
use explicit markers; the exact legacy trailing `Session Closed` shape remains
compatible. The CLI-owned close gate report identifies the record format, so
normalization accepts only that format's exact reconstructed suffix. Malformed,
partial, field-tampered, or provenance-mismatched blocks are not excluded. A
successful close therefore preserves the review that authorized it, while later
changes to evidence, decisions, human-maintained memory, final scope, or ledger
notes still make the review stale.

The pack omits expected `missing_review` and `missing_semantic_review` findings
because the reviewer is being asked to produce that review. The accompanying
gate details remain complete, and all other deterministic evidence, artifact,
memory, decision, and integrity findings remain available to the reviewer.

Keep semantic-review prompts concise but action/profile/mode-aware. Ask the
reviewer for a verdict recommendation, memory fidelity, next-action
recommendation, and short structured findings using the review-pack schema.
For close, memory fidelity includes whether the recorded active, blocked,
deferred, and open-question state will remain truthful after transition.

Semantic review is part of the default gate contract for `full-review`, close,
and phase-gate cases. Semantic findings should be produced from the review pack
or a completed adapter review and surfaced through normal `rdl review`,
`rdl doctor`, `rdl next`, and `rdl close` flows, not as a separate remembered
ceremony.

Review adapters include independent subagents, `phase-review`, manual review,
and project reviewers. The preferred clean-context adapter is an independent
reviewer agent when available. If an independent reviewer cannot be created,
use another explicit adapter when one is available; otherwise stop and report
the tooling or review blocker. The orchestrated `rdl-orchestrator` path is
stricter: it requires subagents and records `Review Mode: subagent` unless the
user explicitly supplies an external adapter result.

The first semantic adapter is read-only over completed `review.md` records. It
surfaces the adapter, reviewed artifacts, staleness/evidence risk, and
review-blocking findings through `details["gate"]["semantic"]`. Its
`subject_binding` is `matched`, `stale`, or legacy `unbound`. `next` and
`close` require an action-matched binding; `doctor` may validate the recorded
review action. A stale required review blocks the gate. A stale optional
lightweight review warns and its old verdict is not consumed for the changed
subject.

If a closed session later becomes stale, restore the reviewed terminal records
or start a new reviewed session. Do not rewrite the closed review binding to
bless post-close drift.

For phase gates, close decisions, and substantial `full-review` rounds, record
the semantic review adapter in `Review Mode` and capture its findings in
`review.md`.

Record returned semantic findings under `Returned Review Findings` using:

```text
- severity | category | location | claim | required_resolution
```

Record accepted corrections separately. RDL may surface these records in gate
details but must not infer that a semantic issue is truly resolved.

After accepted corrections, regenerate the same action-aware pack. If its
digest changed, obtain one delta confirmation and replace the recorded action
and digest. If only `review.md` changed, the digest remains valid.

In every `full-review` round, record whether the round produced fresh evidence
and whether the current direction is becoming stale. In lightweight rounds,
create `review.md` only when there is real review value; if it exists, it must
be complete and aligned with `decision.md`.

When staleness appears, continue only with an explicit stall response, or change
direction with prior directions checked.

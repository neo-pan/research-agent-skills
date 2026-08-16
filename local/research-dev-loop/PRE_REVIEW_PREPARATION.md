# Pre-review Preparation

Use this when the review pack lacks decisive artifact content. It is a workflow template, not a schema or readiness gate; RDL does not judge semantic coverage.

An artifact binds file identity, but its bytes are never copied into the pack. The reviewer sees projected metadata only. Put decisive bounded content in a concise receipt frozen and bound as below.

1. Drive selection from `reviewer_task.questions`. For `close`, cover each `mission.success_criteria`; for `next`, cover `action_context`, the current decision, and unfinished boundaries.
2. The parent, or at most one explorer, may inspect only registered artifact IDs and paths present in the pack. Verify observed size_bytes and sha256 against the registered identity before opening, reading, inspecting, or excerpting content. If verification fails, do not use the content; the registered identity stands as history, so register the current bytes as a new artifact and freeze new evidence citing it. Never inspect or excerpt unbound bytes.
3. Freeze one bounded snapshot receipt, apply it as ordinary artifact/evidence, and regenerate the pack and digest before spawning the semantic reviewer.

The receipt should report, per supplied question:

- support, counterevidence, uncertainty, unfinished progress, blockers, and precise locators;
- artifact identity, query or selector, and match count, truncation, and zero-match scope;
- material omissions without raw search logs, transcripts, or bulk artifact content.

The identity comparison protects the source binding; do not precompute integrity fields for the new receipt because `apply` records them. The semantic reviewer remains clean-spawned, pack-only, tool-free, and responsible for judging whether the receipt is sufficient. A semantic defect may still require new evidence and a changed-digest review.

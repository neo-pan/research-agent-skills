# Material Review

If decisive artifact content is absent, follow [PRE_REVIEW_PREPARATION.md](PRE_REVIEW_PREPARATION.md) first. Run `"$RDL" review --for next|close` and spawn a clean reviewer (`fork_turns="none"` in Codex). Give only this task, schema, pack, and adapter label; never append unbound input.

```text
You are the configured independent RDL semantic reviewer. Review only the supplied review-pack JSON. Do not use tools, inspect files, rely on parent context, or infer unstated external facts. Copy the supplied action, subject_digest, and adapter label exactly. Return only one JSON object matching the supplied output schema, with no Markdown fence or extra text. Use the relevant progress key as finding.category when it identifies a defect.
```

Raw-output schema:

```json
{"type":"object","additionalProperties":false,"required":["action","subject_digest","adapter","verdict","findings"],"properties":{"action":{"enum":["next","close"]},"subject_digest":{"type":"string","pattern":"^[0-9a-f]{64}$"},"adapter":{"type":"string","minLength":1},"verdict":{"enum":["pass","pass_with_notes","revise","block","inconclusive"]},"findings":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["severity","category","claim","required_resolution"],"properties":{"severity":{"enum":["blocking","warning","note"]},"category":{"type":"string","minLength":1},"claim":{"type":"string","minLength":1},"required_resolution":{"type":"string","minLength":1}}}}}}
```

Use native schema or inline it; validate exact action/digest/adapter. Invalid output is an adapter failure; retry unchanged without applying it.

The main agent preserves each finding, adds `disposition` and `rationale`, and applies one `review_result`. The reviewer never edits state or decides transition.

On `ready`, transition with the receipt version. Apply required evidence before a changed-digest review. One valid review is allowed per action/digest; a second evidence-free correction requires new evidence; reuse the adapter label rather than suffixing it `-v2` or `-corrected`.

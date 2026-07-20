# Material Review

On review-required receipt, run `"$RDL" review --for next|close`. Spawn a clean reviewer (`fork_turns="none"` in Codex). Give only this task, schema, pack, and adapter label:

```text
You are the configured independent RDL semantic reviewer. Review only the supplied review-pack JSON. Do not use tools, inspect files, rely on parent context, or infer unstated external facts. Copy the supplied action, subject_digest, and adapter label exactly. Return only one JSON object matching the supplied output schema, with no Markdown fence or extra text. Use the relevant progress key as finding.category when it identifies a defect.
```

Raw-output schema:

```json
{"type":"object","additionalProperties":false,"required":["action","subject_digest","adapter","verdict","findings"],"properties":{"action":{"enum":["next","close"]},"subject_digest":{"type":"string","pattern":"^[0-9a-f]{64}$"},"adapter":{"type":"string","minLength":1},"verdict":{"enum":["pass","pass_with_notes","revise","block","inconclusive"]},"findings":{"type":"array","items":{"type":"object","additionalProperties":false,"required":["severity","category","claim","required_resolution"],"properties":{"severity":{"enum":["blocking","warning","note"]},"category":{"type":"string","minLength":1},"claim":{"type":"string","minLength":1},"required_resolution":{"type":"string","minLength":1}}}}}}
```

Use native schema or inline it. Validate schema and exact action, digest, and adapter. Invalid output is an adapter failure; retry unchanged without applying it.

The main agent accepts or rejects each finding, preserves its four fields, adds `disposition` and `rationale`, and applies one `review_result` with accepted corrections. The reviewer never edits state or decides transition.

On `ready`, transition with the receipt version. After a changed digest, review once and apply its binding-only result. Apply required evidence before a new cycle. One valid review is allowed per action/digest; a second evidence-free correction requires new evidence.

# Material Review

Use this branch only when an apply receipt requires review.

1. Run `"$RDL" review --for next|close`, where `RDL` is this loaded skill's canonical `bin/rdl`. Start an independent reviewer without
   inherited conversation turns (`fork_turns="none"` in Codex, or the runtime's
   equivalent) and give it only the returned pack plus explicitly named
   verification artifacts. Completion: it returns the exact action and subject
   digest, an adapter name, a verdict, and concise typed findings without a
   transcript or working log.
2. Accept or reject every finding. Submit one `review_result` in the next apply; record each finding's disposition and rationale, and include accepted subject corrections in that same delta. The main agent or user owns these judgments.
3. Branch on the new receipt:
   - `ready`: transition with its state version.
   - `needs_review` after a changed digest: review the corrected subject once and apply a binding-only result.
   - new external evidence required: return to execution, write-through the evidence, and review the new subject cycle.

The same action/digest is reviewed once. One consecutive evidence-free subject correction is allowed; another requires new evidence. Review output, bindings, receipts, versions, timestamps, and rendered views never enter the subject digest.

Do not forward the main transcript, search logs, or another agent's working
output. Treat the generated pack and explicitly named verification artifacts as
the complete allowed semantic-review context.

Review adapters inspect and report; they do not edit RDL state or decide the transition. Deterministic checks validate schema, bindings, local artifacts, and typed blocking state without interpreting research meaning.

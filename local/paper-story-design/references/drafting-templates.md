# Optional drafting templates

Use placeholders for unknown values (`[N]`, `[MODEL]`, `[METRIC]`, `[SCORE]`);
never fill them from memory.

## Story and teaser

```text
This paper argues that [long-term goal] requires [core capability]. Existing
work does not systematically characterize it, so we introduce [method/data]
and evaluate [bounded setting].
```

```text
Figure 1 plan: Problem/Input -> Challenges -> Framework -> Key finding.
Label the input, output, challenge names, main modules, and one empirical
finding. A pipeline figure should show source, construction, validation,
inference/training, evaluation or feedback, and final output; do not duplicate
the pipeline with a component figure.
```

## Evidence tables and cases

```markdown
> **Table X.** [Comparison target, metric direction, and claim supported.]

| System | [Challenge 1] | [Challenge 2] | [Metric] |
| --- | --- | --- | ---: |
| Prior A | partial | no | [value] |
| Ours | yes | yes | [value] |
```

For a main-text case, show only `ID`, input summary, gold, output excerpt,
score, and diagnosis. Put full input/output, rubric, score items, and figures
in the appendix; do not silently truncate a case record.

## Section skeleton

- Introduction: background/gap -> related-work distinction -> challenges ->
  method response -> findings -> parallel contributions.
- Method: task/input-output -> design -> constraints -> role in the claim.
- Evaluation: setting and invalid-output handling -> main result -> aligned
  ablation -> analysis/error case.
- Abstract and conclusion: one compact, supported argument; introduce no new
  result in the conclusion.

## Markdown math and citations

Use a fenced `math` block for long or multi-line GitHub formulas; keep formulas
out of tables when possible. Prefer stable forms such as `y_{1:t-1}` over
`y_{<t}` and `\mathrm{KL}` over unsupported macros. Keep citations next to the
claim they support, verify that they are real, and manage LaTeX references in
`.bib` rather than hand-written bibliography text.

---
name: paper-submission-audit
description: Perform a read-only venue-compliance and desk-reject risk audit of a LaTeX submission and its rendered PDF.
---

# Paper submission audit

This is a review-only skill. Do not edit the manuscript, template, metadata, or
build output. If a fix is needed, report the smallest action and let a separate
implementation step make it.

## Audit inputs

Use `references/page-risk-audit-template.md` for the required global and
per-page result shape.

- submission stage and target venue;
- the current official requirements memo and source URLs;
- pristine/current template diff;
- source content inventory and current LaTeX/PDF build receipts;
- rendered PDF pages and, when applicable, source ZIP contents.

If an official rule is unknown, record an Open Question rather than guessing.
Use official venue sources for current rules.

## Checks

- page limit, references/appendix/supplement counting and required files;
- class/style/template integrity, compiler, margins, fonts, columns, line
  numbers, header/footer and caption placement;
- author, affiliation, email, ORCID, funding, acknowledgement, project name,
  private path, PDF metadata and filename leakage;
- external links, code/data/demo URLs, self-identification language and source
  ZIP comments or filenames;
- missing or low-resolution figures, tables, equations, algorithms, cases,
  proofs, key footnotes, citations, and experimental evidence;
- text/figure/caption/formula overlap, overflow, unreadable tables, excessive
  compression, isolated headings, and conspicuous main-body blank space.

Inspect every rendered page. Record each risk as `OK`, `N/A`, or a concrete
finding with page/section locator, why it matters, and the minimal remediation.
Keep references' natural short tails separate from main-body page-fill checks.

## Output and integration

Produce a requirements checklist and `page-risk-audit.md` (or an equivalent
review receipt) without changing source files. State the PDF, page count,
render command, audit date, unresolved questions, and whether the evidence is
sufficient for submission. For a material build, bind the receipt and current
diff/verification artifacts in RDL. This audit does not itself authorize
`next`/`close` and does not replace `phase-review` or the configured project
reviewer.

---
name: paper-submission-audit
description: Perform a read-only venue-compliance and desk-reject risk audit of a LaTeX submission and its rendered PDF.
---

# Paper submission audit

This is a review-only skill. Preserve the manuscript, template, submitted PDF,
and source archive. Generate page images or other inspection artifacts in a
separate temporary/audit directory. Report the findings before proceeding to
any separately authorized implementation step.

## Audit inputs

- submission stage and target venue;
- the current official requirements or project memo with source URLs;
- pristine/current template diff;
- source content inventory and current LaTeX/PDF build receipts;
- rendered PDF pages and, when applicable, source ZIP contents.

Use official venue sources to resolve missing or conflicting rules. Mark a
check `Unverified` when its rule or supporting artifact is unavailable, and
state what is needed to complete it.

## Checks

- page limit, references/appendix/supplement counting and required files;
- class/style/template integrity, compiler, margins, fonts, columns, line
  numbers, header/footer and caption placement;
- stage-specific identity and link compliance: authors, affiliations, funding,
  acknowledgements, self-citations, project/code/data URLs, PDF metadata, and
  source ZIP comments or filenames; also check for private paths and credentials;
- missing or low-resolution figures, tables, equations, algorithms, cases,
  proofs, key footnotes, citations, and experimental evidence;
- text/figure/caption/formula overlap, overflow, unreadable tables, excessive
  compression, isolated headings, and conspicuous main-body blank space.

Inspect every rendered page and state the pages actually covered. Report
findings with a page/section locator, impact, and minimal remediation. Summarize
successful checks by category; reserve `N/A` for inapplicable checks. Distinguish
venue violations from optional presentation improvements; a short page or
natural reference tail alone is not a compliance failure.

## Output and integration

Produce a concise audit receipt with a conclusion, coverage, findings, and
unverified items. Use [references/page-risk-audit-template.md](references/page-risk-audit-template.md)
when a saved report is useful; a full per-page matrix is optional. Identify the
audited PDF/build, page count, render command, and audit date. State whether
the checked requirements are satisfied and whether gaps prevent a readiness
conclusion.

If an authorized RDL session governs this task, record the receipt there;
otherwise include it in the handoff. Any required independent review follows
the user or project workflow.

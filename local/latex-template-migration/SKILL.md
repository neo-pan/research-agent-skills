---
name: latex-template-migration
description: Migrate a LaTeX paper to an explicitly selected venue template while preserving research content and template integrity.
---

# LaTeX template migration

Use this skill for an explicitly named submission, camera-ready, journal
revision, or arXiv template migration. Confirm the stage before changing
anything; do not assume every paper is a double-blind submission.

## Before editing

1. Read the target venue's current official author instructions, author kit,
   sample paper, submission checklist, and template notes. Record URL, access
   date, compiler, columns, page rules, anonymity, captions, references,
   appendix/supplement, checklist, metadata, and source-upload requirements in
   a project-local requirements memo.
2. Inventory the source entry file, section inputs, figures, tables, equations,
   algorithms, case/proof material, footnotes, bibliography, appendix, and
   supplementary files. Compile the source baseline and record PDF page count,
   warnings, and rendered pages.
3. Keep a pristine copy of the official class/style/template files. Work in a
   project-local build directory and do not modify official template files.

Use `references/submission-requirements-template.md` for the memo structure.
For a submission-stage migration, do not infer anonymity or link permission
from the source paper; record the venue rule and run `paper-submission-audit`
before declaring the result ready. Camera-ready and revision stages may have a
different identity policy.
When a current AI/ML venue example is useful, start with
`references/venue-snapshots.md`, then re-check the linked official pages and
record the target venue's own access date. A snapshot is not a substitute for
the target venue's author kit or submission system.

## Migration boundary

- Replace only the document class/options, template wrappers, bibliography
  setup, float environments, and local preamble needed by the target.
- Reuse source section files where possible. Preserve prose, claims, numbers,
  citations, figures, tables, equations, algorithms, cases, proofs, and key
  footnotes.
- Adapt float placement, local dimensions, equation wrappers, and table/image
  sizing for the target columns. Keep tables as tables and evidence figures as
  figures; do not turn them into prose.
- Do not change global line spacing, body font, margins, text block, or official
  class/style behavior unless the venue explicitly requires it.
- Never use negative spacing around title, `\\maketitle`, anonymous author
  blocks, or the abstract's template-reserved area.
- Any anonymization, link removal, acknowledgement change, or mandatory
  statement is a separate, recorded submission-safety change—not silent prose
  editing.

## Page reduction

After stage-1 migration compiles cleanly, reduce pages in this order:

1. float placement and local figure/table/equation spacing;
2. local table spacing, caption spacing, and readable dimensions;
3. only with explicit user authorization, low-risk wording such as repeated
   captions or transition sentences;
4. if still over the limit, report the exact deficit and ask whether to move,
   remove, or restructure material.

Do not delete or weaken main results, ablations, settings, analysis, formulas,
algorithms, cases, proofs, or other evidence to meet a page target silently.
Restore compressed text from the source manuscript, not model memory.

## Verification and handoff

Every meaningful iteration must compile with the venue-required compiler,
inspect fatal/undefined/overfull/float/bibliography warnings, compare content
and template diffs, and render the PDF for visual inspection. Keep the command,
exit status, diff summary, page count, and visual findings as receipts. For a
material build, write them through the active RDL session before `next` or
`close`; use `paper-submission-audit` for the read-only final audit and
`phase-review`/the project reviewer for the final gate.

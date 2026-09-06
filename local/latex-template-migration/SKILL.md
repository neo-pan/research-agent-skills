---
name: latex-template-migration
description: Migrate a LaTeX paper to an explicitly selected venue template while preserving research content and template integrity.
---

# LaTeX template migration

Use this skill for an explicitly named submission, camera-ready, journal
revision, or arXiv template migration. Establish the target and stage from the
request and project context; clarify only if they remain ambiguous.

## Before editing

1. Use a current project requirements memo or consult the target venue's
   official author instructions and linked author kit. Record source URLs,
   access date, and rules needed for this stage, including compiler, page
   limits, identity policy, and required files. Resolve missing or conflicting
   rules against the official sources.
2. Inventory the source entry file, section inputs, figures, tables, equations,
   algorithms, case/proof material, footnotes, bibliography, appendix, and
   supplementary files. Compile the baseline and record existing failures or
   warnings so they can be distinguished from migration regressions.
3. Keep official class/style files pristine and make source changes reviewable
   against the baseline. Isolate generated outputs using `latex-compiling`.

Use [references/submission-requirements-template.md](references/submission-requirements-template.md)
when creating a memo. Identity and link permissions come from the target stage's
rules, not the source manuscript.

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
- Preserve the template's title, author, and abstract spacing.
- Any anonymization, link removal, acknowledgement change, or mandatory
  statement is a separate, recorded submission-safety change—not silent prose
  editing.

## Page reduction

Once the migrated version compiles, reduce pages only if needed for the target:

1. Adjust float placement and readable local dimensions or spacing within venue
   rules.
2. If wording edits are within the user's authorized scope, shorten repetition
   while preserving claims and evidence.
3. Report any remaining page deficit and propose the smallest content change;
   obtain authorization only if it exceeds the agreed editing scope.

Do not delete or weaken main results, ablations, settings, analysis, formulas,
algorithms, cases, proofs, or other evidence to meet a page target silently.
Restore compressed text from the source manuscript, not model memory.

## Verification and handoff

During iteration, compile as needed and inspect affected pages and warnings.
Before handoff, compile with the required toolchain, compare content and template
diffs against the baseline, and inspect every rendered page. Report the command,
exit status, page count, content preservation, and unresolved issues. State
whether template migration is complete; claim submission readiness only when
the applicable requirements have also been checked.

Use `paper-submission-audit` when a separate submission audit is requested.
Run independent review only when required by the user or project workflow.
If an authorized RDL session governs this task, record the verification there;
otherwise include it in the handoff.

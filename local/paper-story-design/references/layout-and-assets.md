# Optional LaTeX layout and assets

Read this reference only after the semantic story is stable and the user asks
for visual or LaTeX adaptation.

- Put teaser/pipeline/component figures where they explain the argument; do not
  duplicate one figure's purpose in another.
- Keep main-result, ablation, setting, and analysis evidence in readable table
  form unless the user explicitly approves a different presentation.
- Prefer local float placement, table spacing, caption spacing, and wrapper
  changes before any global typography or margin changes.
- Keep official venue class/style files untouched; use the existing
  `latex-template-migration` and `paper-submission-audit` workflows for formal
  template and PDF checks.
- Use logos or visual assets only when they serve navigation or an explicitly
  requested style. Do not add asset files, external links, or branding by
  default; verify licenses and anonymity before inclusion.
- Optional resource icons (for example page, GitHub, or Hugging Face) belong
  beside an explicitly permitted resource link; provider/model logos belong
  only beside the model name in a comparison table. Existing approved assets
  may be referenced by local project paths, but this skill does not bundle or
  invent them.
- For GitHub Markdown math, follow the target renderer rather than copying
  LaTeX-only syntax. For PDF page rendering, use `latex-compiling` outputs.

If a figure or table really overflows, adjust float placement or local spacing
first. Do not fix a visual defect by changing claims, values, captions, global
margins, or the venue class. Keep a table's semantic form: comparison tables
use `yes/partial/no` only for attributes, while result tables retain numeric
metrics and mark direction (`higher/lower is better`) in the caption.

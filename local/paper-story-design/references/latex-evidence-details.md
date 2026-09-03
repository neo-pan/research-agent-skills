# Optional LaTeX evidence details

Read only for concrete LaTeX adaptation after the story is stable. These are
project patterns, not venue rules; route template and compliance decisions to
`latex-template-migration` and `paper-submission-audit`.

## Local table patterns

```latex
% Requires \usepackage{booktabs}; define any marker macros before use.
\begingroup
\small
\setlength{\tabcolsep}{4pt}
\renewcommand{\arraystretch}{1.08}
% Keep values, directions, and comparison columns readable.
\begin{tabular}{@{}lccc@{}}
\toprule
System & Overall$\uparrow$ & Error$\downarrow$ & Notes \\
\midrule
Prior & [value] & [value] & [setting] \\
\textbf{Ours} & [value] & [value] & [setting] \\
\bottomrule
\end{tabular}
\endgroup
```

Use `\cmark`, `\pmark`, and `\xmark` only for attribute comparisons, with a
caption legend; define them locally or use the project's existing definitions.
Keep numeric main results separate. Heatmaps and logos are
optional; if used, keep one consistent scale and put a logo only beside the
model name, never in every metric cell.

## Float and contribution checks

Fix overflow by changing local float placement or spacing before touching
global typography. A compact contribution list may use `paralist`'s
`compactitem`, but retain 3--5 parallel, noun-led contributions. Do not delete
evidence or alter values to repair a short tail or page break.

## Appendix cases

Appendix order is usually settings/parse rules, supplementary results, then
full cases. A full case should retain meta info, task/input, data, rubric,
generated report, figures, score items, and reasoning. A breakable `tcolorbox`
can separate these blocks; split across boxes or pages rather than truncating.

## Citation and asset guardrails

Use `.bib`/BibTeX and place citations next to the supported claim. Keep abstract
citations rare and avoid external links in anonymous submissions. Model or
resource logos require real local files, a stable path, license/anonymity
checks, and an explicit readability benefit; no bundled branding is assumed.

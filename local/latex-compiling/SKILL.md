---
name: latex-compiling
description: Compile a LaTeX research project with an isolated build directory, TeX cache, and reproducible verification receipts.
---

# LaTeX compiling

Use this skill when a research or paper project must be compiled with a system
TeX toolchain while keeping generated files out of the source tree.

## Contract

- Start with the project's build command and configuration. Identify the entry
  file, working directory, compiler, and bibliography tool before adapting it.
  Use the existing TeX environment; installation is a separate action.
- Put the PDF, intermediate files, logs, and TeX caches in a project-local
  build directory such as `build/latex/`.
- Set writable `TEXMFVAR` and `TEXMFCONFIG` below that build directory.
- For compile-only requests, report the smallest failure and its evidence
  without editing source, templates, or bibliography. If the user also
  authorized fixing compilation errors, preserve the failing receipt, make
  the smallest in-scope repair, and verify the result. Preserve research
  content and official template integrity.

## Example command

If no build command exists, this example runs from the project root with
`latex/main.tex` as the entry file. `-cd` makes relative inputs resolve from
`latex/`; use the project's actual working-directory convention:

```bash
mkdir -p build/latex/texmf-var build/latex/texmf-config
TEXMFVAR="$PWD/build/latex/texmf-var" \
TEXMFCONFIG="$PWD/build/latex/texmf-config" \
latexmk -cd -pdf -interaction=nonstopmode -halt-on-error \
  -outdir="$PWD/build/latex" latex/main.tex
```

Replace `main.tex`, compiler, and paths with the project/venue contract. For
XeLaTeX/LuaLaTeX or biber, use the required `latexmk` configuration rather
than guessing a different bibliography workflow.

## Verification

Check the exit status and current build log for fatal errors, emergency stops,
undefined control sequences, missing figures, undefined references/citations,
overfull boxes, and bibliography failures. Confirm that the expected PDF in the
build directory belongs to this successful build, rather than an earlier run.
When layout matters, inspect page count and render the relevant pages:

```bash
pdfinfo build/latex/main.pdf | sed -n '1,80p'
pdftoppm -f 1 -l 1 -png -r 180 build/latex/main.pdf build/latex/page
```

Adjust the page range to the change; inspect all pages for a final layout check.
Report the working directory, command, exit status, PDF path, decisive warnings,
and any visual checks performed. Distinguish compilation success from unresolved
reference or layout problems. If an authorized RDL session governs this task,
record the receipt there; otherwise include it in the handoff.

## Cleanup

For this example, `latexmk -cd -c -outdir="$PWD/build/latex" latex/main.tex`
removes intermediates while keeping the PDF. Use `-C` to remove the PDF too.
Keep the same build paths and project configuration.

If a package/style is missing, use an already authorized setup step, or report
it and request the specific environment change needed. For cache failures,
check that the two `TEXMF*` directories are writable.

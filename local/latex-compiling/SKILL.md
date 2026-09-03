---
name: latex-compiling
description: Compile a LaTeX research project with an isolated build directory, TeX cache, and reproducible verification receipts.
---

# LaTeX compiling

Use this skill when a research or paper project must be compiled with a system
TeX toolchain while keeping generated files out of the source tree.

## Contract

- Prefer an existing system `latexmk`/`pdflatex` (or the compiler required by
  the venue); do not install system packages implicitly.
- Put the PDF, intermediate files, logs, and TeX caches in a project-local
  build directory such as `build/latex/`.
- Set writable `TEXMFVAR` and `TEXMFCONFIG` below that build directory.
- Do not edit source files, templates, or bibliography data merely to make a
  compile pass. Report the smallest failure and its evidence.
- Do not place credentials, private links, or downloaded packages in the
  project tree.

## Standard command

From the project root, assuming the entry file is `latex/main.tex`:

```bash
mkdir -p build/latex/texmf-var build/latex/texmf-config
TEXMFVAR="$PWD/build/latex/texmf-var" \
TEXMFCONFIG="$PWD/build/latex/texmf-config" \
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  -outdir="$PWD/build/latex" latex/main.tex
```

Replace `main.tex`, compiler, and paths with the project/venue contract. For
XeLaTeX/LuaLaTeX or biber, use the required `latexmk` configuration rather
than guessing a different bibliography workflow.

## Verification

Check the exit status and inspect the log for fatal errors, emergency stops,
undefined control sequences, missing figures, undefined references/citations,
overfull boxes, and bibliography failures. Confirm that the expected PDF is in
the build directory and inspect its page count and rendered pages when layout
matters:

```bash
pdfinfo build/latex/main.pdf | sed -n '1,80p'
pdftoppm -png -r 180 build/latex/main.pdf build/latex/page
```

Keep the command, exit status, decisive log lines, PDF path, page count, and
visual-check result together as a small receipt. For a material build, record
that receipt and the PDF/log/page images through the active RDL session before
claiming a transition or close. A compile receipt proves compilation only; it
does not replace `phase-review` or the configured project reviewer.

## Cleanup

Use `latexmk -c -outdir="$PWD/build/latex" latex/main.tex` to remove
intermediates while keeping the PDF, or replace `-c` with `-C` when the PDF
should also be removed. Never
run a bare compiler in the source directory unless the project explicitly
requires it and the generated files are immediately isolated or cleaned.

If a package/style is missing, report the missing dependency and ask for the
approved environment change. If TeX cache creation fails, verify that the two
`TEXMF*` directories are writable before changing anything else.

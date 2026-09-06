# Optional Overleaf operational details

## Browser parameters

In the logged-in browser, use Developer Tools -> Network, open the target
project, and inspect its ZIP download request. Copy the request URL and Cookie
into shell environment variables or a restrictive temporary cookie file; do
not paste the Cookie into chat, commit it, or put it in the project tree.
The helper accepts only HTTPS URLs on `overleaf.com` or `www.overleaf.com` and
normalizes the bare host to `www.overleaf.com` before sending the Cookie.

## Ignore policy

The helper's defaults ignore Git metadata, caches, compiler output, and common
agent files. If a repository also keeps local maintenance scripts, notes, raw
data, or backups that must not participate in sync, add narrow project-specific
patterns, for example:

```bash
--ignore 'build/latex/**' --ignore 'backups/**'
```

Do not use broad ignores to hide paper source files accidentally. Use
`--no-default-ignores` only when intentionally comparing ignored content.

For DNS, timeout, or proxy failures, inspect the current proxy environment and
retry only with an approved network configuration; do not put credentials in a
retry command or change long-lived shell configuration from this workflow.

## Directory layout

Preserve ZIP paths by default: `latex/main.tex` stays `latex/main.tex` under the
target. If the archive instead has a known wrapper such as
`downloaded-project/latex/main.tex`, pass `--strip-single-root` to both `check`
and `update` to remove that wrapper. The flag requires a single top-level
directory. It replaces the former default stripping behavior and
`--no-strip-single-root` option.

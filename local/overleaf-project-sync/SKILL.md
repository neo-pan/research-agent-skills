---
name: overleaf-project-sync
description: Explicitly compare or update a local LaTeX project from an Overleaf ZIP without exposing credentials or deleting local files.
---

# Overleaf project sync

Use this skill only when the user explicitly wants to inspect or copy an
Overleaf project. The helper script is read-only by default.

## Credential and write boundary

- Obtain the ZIP URL and Cookie in the user's browser session; never ask the
  user to paste a Cookie into chat or commit it to a repository.
- Prefer `OVERLEAF_COOKIE`/`OVERLEAF_ZIP_URL` in the local shell or a temporary
  cookie file with restrictive permissions.
- Run `check` first. `update` without `--overwrite` is still a dry run.
- Only `update --overwrite` writes existing local files; local-only files are
  never deleted. Inspect `git diff --check` and `git status` afterwards.
- Existing symlink or non-file destinations are rejected before any copy.
- The script does not change `PATH`, shell configuration, Git history, or
  install packages. Temporary downloads are cleaned automatically.

## Commands

```bash
python3 /path/to/overleaf-project-sync/scripts/overleaf_sync.py check \
  --target .

python3 /path/to/overleaf-project-sync/scripts/overleaf_sync.py update \
  --target . --dry-run

python3 /path/to/overleaf-project-sync/scripts/overleaf_sync.py update \
  --target . --overwrite
```

The URL and Cookie may instead be supplied with `--url`, `--cookie-file`, or
the corresponding environment variables. Only same-origin redirects are
allowed. Add `--ignore` for project-specific generated files; use
`--no-default-ignores` when the defaults would hide a file that must be compared.
Read [references/operational-details.md](references/operational-details.md) for
browser parameter acquisition and narrow ignore patterns when needed.

For a material paper build, preserve the comparison output and post-update Git
diff as receipts in RDL. A sync receipt does not authorize unrelated source
changes or replace phase/project review.

## Failure handling

HTTP 401/403 normally means an expired or incomplete browser Cookie. Missing
URL/Cookie, an unreadable target, an unsafe ZIP member, or a failed comparison
must stop before any write. Do not retry with credentials in the transcript.

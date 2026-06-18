# Agent Instructions

This repository is a personal skill pack for research engineering workflows
across local projects.

## Repository Rules

- Keep this repository generic. Do not add project-specific benchmark rules,
  machine paths, credentials, downloaded packages, runtime notes, or private
  environment details.
- Treat `selected-skills.conf` as the source of truth for exposed skills.
  Update it before relinking skills.
- Installers must install only skills listed in `selected-skills.conf` or
  exposed through generated `skills/` symlinks. Do not scan
  `upstream/mattpocock-skills` to install every upstream skill.
- Treat `skills/` as generated symlinks. Do not commit generated skill links;
  only `skills/.gitkeep` is tracked.
- Treat `upstream/mattpocock-skills` as a third-party submodule. Do not edit
  files inside it. Update it only with `scripts/update_upstream.sh`, review the
  result, then commit the submodule pointer.
- Put personal skills under `local/<skill-name>/SKILL.md`. Keep local skills
  concise, generic, and reusable across research projects.
- Keep scripts small and dependency-light. Prefer Bash, Git, and standard
  system tools over a package, CLI framework, or generated project scaffold.

## Maintenance Workflow

After changing `selected-skills.conf`, local skills, scripts, or the upstream
submodule, run:

```bash
./scripts/link_selected_skills.sh
./scripts/check.sh
```

For upstream updates:

```bash
./scripts/update_upstream.sh
./scripts/check.sh
git status
```

Commit only reviewed source files, local skills, scripts, manifest changes, and
submodule pointer updates.

## Skill Authoring

- Follow Codex skill-creation principles: make invocation clear, keep
  `SKILL.md` focused, and move only genuinely optional detail into references.
- Use `disable-model-invocation: true` for manual workflow gates or router-like
  skills that should not auto-trigger.
- Avoid adding auxiliary files inside a skill directory unless they directly
  support the skill.
- Prefer review-only skills for gates; implementation should happen in a
  separate step unless the user explicitly asks otherwise.

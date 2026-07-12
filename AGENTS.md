# Agent Instructions

This repository is a personal skill pack for research engineering workflows
across local projects.

## Installer Contract

- Treat the repository root as the only installation entry point.
- Install only after `git submodule update --init --recursive` and
  `./scripts/link_selected_skills.sh`.
- Install from generated `skills/` symlinks, or use
  `./scripts/install_selected_skills.sh <target-skills-dir>`.
- Never install by recursively scanning `upstream/` or by using
  `upstream/mattpocock-skills` as the repository root.
- For Codex RDL orchestration, recommend the reviewed role configurations under
  `codex/agents/` and install them separately with
  `./scripts/install_recommended_codex_agents.sh [target-agents-dir]`.
  Do not make custom-agent installation an implicit side effect of skill
  installation.

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

## RDL Design Principle

- Keep deterministic RDL gates limited to protocol, schema, local artifact
  integrity, and managed-summary facts that can be verified without judging
  research meaning.
- Do not encode semantic judgments as ad hoc parser rules. Questions such as
  whether evidence is decision-grade, an active item is truly stale, a review
  trigger has semantically occurred, session memory faithfully represents
  research state, or a claim overreaches belong in semantic review.
- Treat independent subagents, `phase-review`, manual review, and project
  reviewers as adapters behind the semantic review gate. Record the adapter and
  findings in `review.md` or gate report details; do not add extra user-facing
  ceremony when the normal `rdl review`, `rdl doctor`, `rdl next`, and
  `rdl close` flow can carry the result.
- Preserve single-writer discipline for canonical RDL files. Subagents may
  inspect context and produce findings, but the main agent or user remains
  responsible for accepting judgment-heavy changes to `decision.md`,
  `progress.md`, `factors.md`, and final reports.

## Agent skills

### Issue tracker

Specs, tickets, and wayfinding maps are tracked as local markdown under `.scratch/`. See
`docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the default mattpocock/skills label vocabulary. See
`docs/agents/triage-labels.md`.

### Domain docs

Domain documentation uses a single-context layout with root `CONTEXT.md` and
`docs/adr/`. See `docs/agents/domain.md`.

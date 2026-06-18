# Research Agent Skills

Personal skill pack for research engineering workflows across local projects.

This repository pins external skill sources with git submodules and exposes a
small selected set through local symlinks. It is intended for project
development, experiment orchestration, debugging, architecture, and handoff
work. It is not intended to directly participate in TileLang-Ascend kernel
candidate search.

## Layout

| Path | Purpose |
|---|---|
| `upstream/mattpocock-skills` | Pinned submodule for Matt Pocock's skills. |
| `selected-skills.conf` | Canonical selected skill manifest. |
| `skills/` | Generated symlinks for selected skills. |
| `local/` | Personal local skills, maintained separately from upstream. |
| `scripts/link_selected_skills.sh` | Rebuilds `skills/` symlinks from the selected list. |
| `scripts/check.sh` | Validates the manifest, skill sources, and generated links. |
| `scripts/update_upstream.sh` | Explicitly updates the upstream submodule and relinks. |

## Setup

```bash
git submodule update --init --recursive
./scripts/link_selected_skills.sh
./scripts/check.sh
```

Projects can then link individual skills from this repository's `skills/`
directory, or link the whole directory into a project-specific skill surface.
Different agents discover skills differently; use this repository's `skills/`
directory as the prepared source and follow the target agent or project
convention for exposing those skill directories.

## Update Upstream

Update Matt Pocock's skills explicitly:

```bash
./scripts/update_upstream.sh
git status
git add upstream/mattpocock-skills
git commit -m "Update Matt Pocock skills"
```

The submodule commit is part of this repository's state, so different machines
can reproduce the same selected skill versions after cloning.

On GitHub, the `Update Upstream Skills` workflow can be run manually to open or
update a pull request for the same upstream submodule update and enable GitHub
auto-merge. To make merge wait for approval, protect `main` with a required pull
request review and enable auto-merge for the repository.

## Selected Upstream Skills

The current selected upstream skills are:

- `grill-with-docs`
- `domain-modeling`
- `codebase-design`
- `improve-codebase-architecture`
- `diagnosing-bugs`
- `tdd`
- `to-prd`
- `to-issues`
- `prototype`
- `grill-me`
- `handoff`
- `writing-great-skills`

## Local Skills

The current local skills are:

- `phase-review` - manual independent gate for research engineering plans,
  implementation phases, evidence, and final readiness.

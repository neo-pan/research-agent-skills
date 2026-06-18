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
| `selected-skills.toml` | Canonical selected upstream skill list. |
| `skills/` | Generated symlinks for selected skills. |
| `local/` | Personal local skills or notes, maintained separately from upstream. |
| `scripts/link_selected_skills.sh` | Rebuilds `skills/` symlinks from the selected list. |
| `scripts/update_upstream.sh` | Explicitly updates the upstream submodule and relinks. |

## Setup

```bash
git submodule update --init --recursive
./scripts/link_selected_skills.sh
```

Projects can then link individual skills from this repository's `skills/`
directory, or link the whole directory into a project-specific skill surface.

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

## Selected Skills

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


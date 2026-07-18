# Research Agent Skills

Personal skill pack for research engineering workflows across local projects.

## Install Contract

When installing this repository from a GitHub URL, treat the repository root as
the only installation entry point.

1. Clone the repository with submodules initialized.
2. Run `./scripts/link_selected_skills.sh`.
3. Install from `skills/` or run `./scripts/install_selected_skills.sh`.

Do not install directly from any subdirectory under `upstream/`. The upstream
submodule contains many skills that are intentionally not exposed by this
repository.

This repository pins external skill sources with git submodules and exposes a
small selected set through local symlinks. It is intended for project
development, experiment orchestration, debugging, architecture, and handoff
work. It is not intended to directly participate in TileLang-Ascend kernel
candidate search.

Install only the skills listed in `selected-skills.conf`. Do not scan or install
all skills under `upstream/mattpocock-skills`; that submodule is only a pinned
source for the selected upstream entries.

## Layout

| Path | Purpose |
|---|---|
| `upstream/mattpocock-skills` | Pinned submodule for Matt Pocock's skills. |
| `selected-skills.conf` | Canonical selected skill manifest. |
| `skills/` | Generated symlinks for selected skills. |
| `local/` | Personal local skills, maintained separately from upstream. |
| `codex/agents/` | Recommended Codex role configurations for the RDL orchestrator. |
| `scripts/link_selected_skills.sh` | Rebuilds `skills/` symlinks from the selected list. |
| `scripts/install_selected_skills.sh` | Installs selected skill links into a target skill directory. |
| `scripts/install_recommended_codex_agents.sh` | Installs the recommended RDL Codex role configurations. |
| `scripts/check.sh` | Runs repository checks. |
| `scripts/update_upstream.sh` | Explicitly updates the upstream submodule and relinks. |

## Setup

```bash
git submodule update --init --recursive
./scripts/link_selected_skills.sh
./scripts/check.sh
```

Run `./scripts/check.sh` before committing changes.

Install the selected skills into an agent or project skill directory:

```bash
./scripts/install_selected_skills.sh <target-skills-dir>
```

If no target is provided, the script installs into
`${CODEX_HOME:-$HOME/.codex}/skills`. Different agents discover skills
differently; use `skills/` as the prepared selected source and follow the target
agent or project convention for exposing those skill directories.

### Recommended Codex agents

When using material RDL review or bounded exploration with Codex, install the
repository's optional reviewer and explorer roles:

```bash
./scripts/install_recommended_codex_agents.sh
```

The command links the reviewed configurations from `codex/agents/` into
`${CODEX_HOME:-$HOME/.codex}/agents`. It refuses to replace an existing regular
file. To install them for one trusted project instead, pass that project's
agent directory explicitly:

```bash
./scripts/install_recommended_codex_agents.sh /path/to/project/.codex/agents
```

The recommended role allocation is:

| Role | Model | Reasoning effort | Sandbox |
|---|---|---|---|
| RDL reviewer | `gpt-5.6-sol` | `high` | `read-only` |
| RDL explorer | `gpt-5.6-terra` | `medium` | `read-only` |

For shallow, bounded delegation, also add the following to the applicable user or trusted-project
`config.toml`:

```toml
[agents]
max_threads = 4
max_depth = 1
```

Restart Codex or start a new session after installing or changing custom agent
files. See `local/rdl-orchestrator/CODEX.md` for the role rationale and usage
constraints. Installing these roles is recommended for RDL orchestration but is
not required for using the other skills in this repository.

For shallow clones, initialize submodules before installing:

```bash
git submodule update --init --recursive
```

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

Selection favors stable, general-purpose research-engineering workflows that
compose with the rest of this pack. Skills under upstream `in-progress/`,
ecosystem-specific setup skills, and roles that substantially duplicate an
existing local workflow are not exposed by default.

The current selected upstream skills are:

- `grill-with-docs`
- `domain-modeling`
- `codebase-design`
- `improve-codebase-architecture`
- `diagnosing-bugs`
- `setup-matt-pocock-skills`
- `tdd`
- `to-spec`
- `to-tickets`
- `prototype`
- `wayfinder`
- `grill-me`
- `grilling`
- `handoff`
- `writing-great-skills`

## Local Skills

The current local skills are:

- `phase-review` - manual independent gate for research engineering plans,
  implementation phases, evidence, and final readiness.
- `research-dev-loop` - durable normalized evidence state and a seven-command
  Research Development Loop CLI.
- `rdl-orchestrator` - manual terminal RDL loop with material-only semantic review.

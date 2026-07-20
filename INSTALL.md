# Installation

This repository is installed from the repository root only.

```bash
git clone --recurse-submodules <repository-url>
cd research-agent-skills
./scripts/link_selected_skills.sh
./scripts/install_selected_skills.sh <target-skills-dir>
```

If the repository was cloned without submodules, run this before installing:

```bash
git submodule update --init --recursive
```

The installable skill set is defined by `selected-skills.conf` and materialized
as symlinks under `skills/`. Installers must not scan
`upstream/mattpocock-skills` or install every skill found there.

Python 3.9+ is required by the managed-link installers. Skills and recommended
Codex agents are installed as absolute symlinks. Installation refuses to
overwrite regular files, directories, foreign links, links from a historical
checkout, relative links, or broken links whose ownership cannot be proven.
Only links owned by the current checkout may be replaced or pruned. The full
desired set is checked for conflicts before any link mutation begins.

## Codex installation status

Successful link creation does not guarantee that a later Codex process uses the
same home. Diagnose the prospective launch environment independently:

```bash
./scripts/codex_installation_status.py
./scripts/codex_installation_status.py --json
./scripts/codex_installation_status.py \
  --codex-home /absolute/codex-home \
  --skills-dir /absolute/installed-skills \
  --agents-dir /absolute/installed-agents
```

Codex home precedence is `--codex-home`, `CODEX_HOME`, then `$HOME/.codex`.
The skills and agents directories default under that home; explicit directory
arguments compare another installation to that launch home. The command reports
only filesystem state for a prospective launch. It does not inspect an
already-running process or infer whether a skill is enabled or can be invoked
implicitly.

Output is compact text by default. `--json` returns the stable top-level keys
`status`, `codex_home`, `skills`, `agents`, `rdl_command`, and `findings`.
Exit status is `0` when the requested installation matches, `2` for a missing,
mismatched, broken, or conflicting installation, and `1` for invalid input or
an internal error. An unprepared `skills/` set that does not match
`selected-skills.conf` is invalid repository input rather than an installation
mismatch; run `./scripts/link_selected_skills.sh` before retrying.

To include the optional bare RDL command in the same read-only report, provide
its directory explicitly:

```bash
./scripts/codex_installation_status.py --rdl-bin-dir "$HOME/.local/bin"
```

The status command never guesses a command directory and never installs or
removes the RDL adapter.

## Optional `rdl` command

Skill discovery and shell command discovery are separate. RDL's canonical
repository launcher is `local/research-dev-loop/bin/rdl`; an installed
`research-dev-loop` skill provides the same launcher at its `bin/rdl`. Python
3.9+ on Linux/WSL is required.

The launcher is always usable directly. To expose the optional bare `rdl`
command, choose an existing private directory inside your home that is already
on `PATH`, then manage the symlink explicitly:

```bash
./scripts/install_rdl_command.py status --bin-dir "$HOME/.local/bin"
./scripts/install_rdl_command.py install --bin-dir "$HOME/.local/bin"
./scripts/install_rdl_command.py uninstall --bin-dir "$HOME/.local/bin"
```

`--bin-dir` is always required. The installer never creates a directory, edits
`PATH` or shell startup files, installs Python packages, writes a system
directory, runs a skill hook, chooses an alternate command name, or overwrites an
existing target. Installation also refuses an earlier executable `rdl` on
`PATH`. Status remains read-only even when PATH is malformed or the directory is
not writable; uninstall removes only the exact symlink created by the current
checkout.

Before moving or deleting this checkout, uninstall its adapter. After moving,
install from the new checkout. If the old checkout was already removed and the
adapter is broken, inspect and remove that symlink manually before reinstalling;
the conservative installer does not infer ownership of broken or historical
links. Do not install a public registry package merely because it is named
`rdl`.

The Python launcher is best effort on macOS with a suitable Python, but the
repository's complete Bash installation chain is not claimed to support stock
macOS Bash. Native Windows is unsupported; use WSL.

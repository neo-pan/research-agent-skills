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


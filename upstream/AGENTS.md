# Agent Instructions for `upstream/`

This directory is not an installation entry point.

The `upstream/mattpocock-skills` directory is a pinned third-party submodule
used only as source material for selected skills. Do not install skills by
scanning this directory.

Return to the repository root and install only the selected set:

```bash
./scripts/link_selected_skills.sh
./scripts/install_selected_skills.sh <target-skills-dir>
```

The selected set is defined in `selected-skills.conf` and exposed through the
generated `skills/` symlinks.


# Optional Codex Roles

Install the reviewed configs with `scripts/install_recommended_codex_agents.sh` when independent material review or bounded exploration is useful.

- `rdl-reviewer.toml`: fresh-context, read-only semantic reviewer.
- `rdl-explorer.toml`: optional read-only explorer for one bounded question.

The main agent submits `rdl apply`; no dedicated writer role is required.

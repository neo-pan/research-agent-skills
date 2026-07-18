# Optional Codex Roles

Install the reviewed configs with `scripts/install_recommended_codex_agents.sh` when independent material review or bounded exploration is useful.

- `rdl-reviewer.toml`: fresh-context, read-only semantic reviewer.
- `rdl-explorer.toml`: optional read-only explorer for one bounded question.

The main agent submits `rdl apply`; no dedicated writer role is required.

## Clean Spawn Contract

Start each role without parent conversation turns. With the Codex subagent
adapter, pass `fork_turns="none"`; other adapters must provide an equivalent
clean-spawn option. Custom-agent files cannot enforce launch context.

Give the reviewer only the generated review pack and explicitly named
verification artifacts. Give an explorer one bounded question and only the
context allowed for that question. Do not forward the main transcript, search
logs, or another agent's working output.

Default to no explorer. Use one when isolating a bounded, high-noise question
materially reduces main-context load; use two only for independent questions
that materially benefit from parallel work. Explorers return evidence inputs,
not decisions, and never write shared state or spawn more agents.

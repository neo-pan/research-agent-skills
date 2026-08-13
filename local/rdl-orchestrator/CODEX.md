# Optional Codex Roles

Install the reviewed configs with `scripts/install_recommended_codex_agents.sh` when independent material review or bounded exploration is useful.

- `rdl-reviewer.toml`: fresh-context, read-only semantic reviewer.
- `rdl-explorer.toml`: optional read-only explorer for one bounded question.

The main agent resolves the loaded `research-dev-loop` skill's `bin/rdl` as `RDL` and submits `"$RDL" apply`; no dedicated writer role is required.

## Clean Spawn Contract

Start each role without parent conversation turns. With the Codex subagent
adapter, pass `fork_turns="none"`; other adapters must provide an equivalent
clean-spawn option. Custom-agent files cannot enforce launch context.

Give the reviewer only the task, output schema, generated review pack, and
adapter label. If artifact content is needed, follow the loaded RDL skill's
[preparation reference](../research-dev-loop/PRE_REVIEW_PREPARATION.md), bind its
digest-bound receipt or excerpt through `apply`, and regenerate the pack. Give an
explorer one bounded question and only its allowed context. Do not forward the
main transcript, search logs, or another agent's working output.

Default to no explorer; use at most one when isolating a bounded, high-noise
question materially reduces main-context load. Explorers return evidence
inputs, not decisions, and never write shared state or spawn more agents.

For a material build's final code/config/script claim, use the project's single
configured read-only project reviewer before semantic close review. Prefer a
committed candidate and bind the reviewed diff as the ordered
`git diff <base-commit> <result-commit> -- <reviewed-paths>` comparison;
for necessary pre-commit review, bind the base HEAD, reviewed paths, and Git
blob object ID produced by piping the exact
`git diff --binary --full-index --no-ext-diff HEAD -- <paths>` bytes to
`git hash-object --stdin`, and bind that blob ID to the exact diff byte stream.
Relevant untracked files must enter that Git diff or
the review is incomplete. Do not invent an RDL-specific diff digest. Bind the
project-review and verification receipts through RDL evidence; any relevant
change requires verification and project review again. This reviewer never
performs the RDL transition. Pure research and no-code claims skip this gate
unless the mission explicitly requires it.

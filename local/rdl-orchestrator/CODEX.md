# Optional Codex Role Configuration

Use these configurations only when configuring Codex for `rdl-orchestrator`.
They are non-normative and do not change the RDL protocol. Reviewed source
files live under `codex/agents/` at the repository root. Installing them is
recommended for RDL orchestration:

```bash
./scripts/install_recommended_codex_agents.sh
```

The installer defaults to `${CODEX_HOME:-$HOME/.codex}/agents`; pass a trusted
project's `.codex/agents` directory to scope the roles to that project.

## Global Limits

Keep direct subagents shallow and bounded:

```toml
[agents]
max_threads = 4
max_depth = 1
```

## Role Baselines

Use this quality-first baseline before optimizing role models:

| Role | Model | Reasoning effort |
| --- | --- | --- |
| Main/root | `gpt-5.6-sol` | `medium`; raise to `high` for difficult work |
| Writer | `gpt-5.6-sol` | `medium` |
| Reviewer | `gpt-5.6-sol` | `high` |
| Explorer | `gpt-5.6-terra` | `medium` |

The July 2026 writer calibration did not promote `gpt-5.6-terra`: a repeated,
representative A/B failed the semantic-fidelity and efficiency gates. Keep the
writer on `gpt-5.6-sol` until a new representative calibration shows no
increase in evidence omission, false facts, reviewer corrections, re-review,
or handoff failure and also shows a real latency or token benefit. Keep the
critical reviewer on `gpt-5.6-sol` high by default.

## Writer

Install `codex/agents/rdl-writer.toml`. It is the only role allowed to write
canonical RDL records and returns the compact writer receipt.

Do not change `model` to `gpt-5.6-terra` unless a later writer A/B meets every
promotion criterion above.

## Reviewer

Install `codex/agents/rdl-reviewer.toml`. It is read-only and uses Sol/high for
critical semantic review.

## Explorer

Install `codex/agents/rdl-explorer.toml`. It is read-only and uses Terra/medium
for independent bounded exploration.

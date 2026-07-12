# RDL CLI Reference

Run the Python module from a project repository:

```bash
PYTHONPATH=local/research-dev-loop python3 -m rdl start research mission.md --json
PYTHONPATH=local/research-dev-loop python3 -m rdl start build plan.md --json
PYTHONPATH=local/research-dev-loop python3 -m rdl status --json
PYTHONPATH=local/research-dev-loop python3 -m rdl handoff --json
PYTHONPATH=local/research-dev-loop python3 -m rdl handoff --session-id <id> --json
PYTHONPATH=local/research-dev-loop python3 -m rdl review --pack --json
PYTHONPATH=local/research-dev-loop python3 -m rdl review --pack --for next --json
PYTHONPATH=local/research-dev-loop python3 -m rdl review --pack --for close --json
PYTHONPATH=local/research-dev-loop python3 -m rdl review --pack --for doctor --json
PYTHONPATH=local/research-dev-loop python3 -m rdl review --pack --session-path <path> --json
PYTHONPATH=local/research-dev-loop python3 -m rdl memory --check --json
PYTHONPATH=local/research-dev-loop python3 -m rdl next --mode build --json
PYTHONPATH=local/research-dev-loop python3 -m rdl next --profile checkpoint --json
PYTHONPATH=local/research-dev-loop python3 -m rdl progress active --item parser --text "raw parser capability" --trigger "sample coverage review" --json
PYTHONPATH=local/research-dev-loop python3 -m rdl factors --section "Dataset or Workload" --value "current workload slice" --json
PYTHONPATH=local/research-dev-loop python3 -m rdl record artifact EV1 log artifacts/run.log "parser smoke output" --json
PYTHONPATH=local/research-dev-loop python3 -m rdl record artifact EV2 log src/parser.py "live source path" live-path --json
PYTHONPATH=local/research-dev-loop python3 -m rdl record finding warning evidence rounds/001/evidence.md "coverage is thin" "add fixture evidence" --json
```

When another tool or agent consumes `--json`, run RDL from a clean shell/session
so stdout remains parseable JSON.

Use `review --pack --for next|close|doctor` when the reviewer should assess a
specific intended action. `--for next` evaluates the advance gate but exposes
`next` in the reviewer task. `--for close` infers the outcome from the current
`Decision: close-*` record and returns `missing_close_outcome` when no such
decision is recorded. Omitting `--for` preserves the generic review pack. Each
pack exposes `subject_digest`; record it with the pack `action` as `Review
Subject Digest` and `Review Subject Action` in `review.md`.

RDL requires `python3`. Its implementation lives under
`local/research-dev-loop/rdl/`.

Before committing changes in this skill pack, run:

```bash
./scripts/check.sh
```

That check runs manifest/link checks, RDL Python tests, repository prerequisite
checks, and the dogfood audit.

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from rdl import integrity
from rdl.cli import main
from rdl.session import SessionStore

from rdl_test_support import complete_research_round, create_session


class CliHandoffTests(unittest.TestCase):
    def test_handoff_json_returns_compact_session_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_complete_handoff_session(root)

            code, result = run_cli_json(root, ["handoff", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "handoff")
            self.assertEqual(result["details"]["handoff_status"], "ready")
            self.assertEqual(result["details"]["current_focus"], "- fixture active claim")
            self.assertEqual(result["details"]["last_decision"]["decision"], "continue")
            self.assertEqual(result["details"]["last_decision"]["closes"], "claim")
            self.assertEqual(result["details"]["last_decision"]["recommended_next_loop"], "none")
            self.assertIn("later work", result["details"]["known_evidence_gaps"])
            self.assertEqual(result["details"]["memory"]["memory_status"], "healthy")
            self.assertEqual(result["details"]["gate"]["gate_status"], "needs_attention")
            self.assertEqual(result["details"]["gate"]["memory"]["memory_status"], "healthy")
            self.assertEqual(result["next_action"], "rdl doctor")

    def test_handoff_json_allows_incomplete_current_round_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "handoff_incomplete")
            before = snapshot(session_dir)

            code, result = run_cli_json(root, ["handoff", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["details"]["handoff_status"], "needs_attention")
            self.assertEqual(result["details"]["gate"]["gate_status"], "needs_attention")
            self.assertEqual(result["details"]["last_decision"]["decision"], "none recorded")
            self.assertEqual(result["details"]["memory"]["progress_gaps"], ["Active", "Blocked", "Deferred"])
            self.assertEqual(result["next_action"], "rdl progress active|blocked|deferred|none")
            self.assertEqual(snapshot(session_dir), before)

    def test_handoff_next_action_points_to_memory_write_for_stale_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "handoff_summary")
            session_dir = SessionStore(root).active_session().root
            complete_research_round(session_dir)

            code, result = run_cli_json(root, ["handoff", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["handoff_status"], "needs_attention")
            self.assertEqual(result["next_action"], "rdl memory --write")

    def test_handoff_next_action_points_to_factors_when_only_factor_gaps_remain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "handoff_factors")
            progress = """# Progress

## Active

No active items.

## Completed

No completed items.

## Blocked

No blocked items.

## Deferred

No deferred items.

## Open Questions

## Directions Tried

## Staleness Watch
"""
            (session_dir / "progress.md").write_text(progress, encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli_json(root, ["handoff", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["memory"]["progress_gaps"], [])
            self.assertIn("Model or Algorithm", result["details"]["memory"]["factor_gaps"])
            self.assertEqual(result["next_action"], "rdl factors set|note")

    def test_handoff_json_reports_latest_completed_decision_after_advance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "handoff_after_advance")
            complete_research_round(session_dir, "continue")
            code, result = run_cli_json(root, ["next", "--json"])
            if code != 0:
                raise AssertionError(result)
            before = snapshot(session_dir)

            code, result = run_cli_json(root, ["handoff", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["last_decision"]["decision"], "none recorded")
            self.assertEqual(result["details"]["latest_completed_decision"]["round"], 1)
            self.assertEqual(result["details"]["latest_completed_decision"]["decision"], "continue")
            self.assertEqual(result["details"]["latest_completed_decision"]["closes"], "claim")
            self.assertEqual(snapshot(session_dir), before)

    def test_handoff_blocks_without_active_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, result = run_cli_json(Path(tmp), ["handoff", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blockers"][0]["code"], "no_active_session")

    def test_handoff_text_output_is_human_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_complete_handoff_session(root)

            code, output = run_cli_text(root, ["handoff"])

            self.assertEqual(code, 0)
            self.assertIn("Session: handoff_complete", output)
            self.assertIn("Current Focus:", output)
            self.assertIn("Last Decision:", output)
            self.assertIn("Latest Completed Decision:", output)
            self.assertIn("  decision: continue", output)
            self.assertIn("Memory:", output)
            self.assertIn("Suggested Actions:", output)
            self.assertNotIn("ok: handoff", output)


def create_complete_handoff_session(root: Path) -> Path:
    session_dir = create_session(root, "handoff_complete")
    complete_research_round(session_dir)
    progress = """# Progress

## Active

| Item | Mode | Claim or Capability | Blocking? | Next Review Trigger |
|---|---|---|---|---|
| active-claim | research | fixture active claim | no | next evidence review |

## Completed

| Item | Decision | Evidence | Round |
|---|---|---|---|
| fixture | continue | fixture evidence | 001 |

## Blocked

| Item | Reason | Needed Evidence or Input | Decision Impact |
|---|---|---|---|
| no blocked items | none | none | none |

## Deferred

| Item | Reason | Revisit Trigger |
|---|---|---|
| no deferred items | none | none |

## Open Questions

| Question | Owner | Blocking? | Resolution |
|---|---|---|---|

## Directions Tried

| Direction | Rounds | Outcome | Why Not Repeat |
|---|---|---|---|

## Staleness Watch

| Signal | Evidence | Response |
|---|---|---|
"""
    factors = """# Factors

## Model or Algorithm
fixture model
## Dataset or Workload
fixture workload
## Seed and Sampling
fixture seed
## Hardware or Backend
fixture backend
## Prompt or Policy Version
fixture prompt
## Baseline
fixture baseline
## Candidate-Visible Context
fixture context
## Metric Definition
fixture metric
## Evaluator or Validator Version
fixture validator
## Environment
fixture environment
## Known Non-Determinism
none
"""
    (session_dir / "progress.md").write_text(progress, encoding="utf-8")
    (session_dir / "factors.md").write_text(factors, encoding="utf-8")
    integrity.refresh(SessionStore(root).active_session())
    code, result = run_cli_json(root, ["memory", "--write", "--json"])
    if code != 0:
        raise AssertionError(result)
    return session_dir


def snapshot(session_dir: Path) -> dict[str, str]:
    return {
        "progress": (session_dir / "progress.md").read_text(encoding="utf-8"),
        "ledger": (session_dir / "decision-ledger.md").read_text(encoding="utf-8"),
        "integrity": (session_dir / "integrity.json").read_text(encoding="utf-8"),
    }


def run_cli_json(root: Path, argv: list[str]) -> tuple[int, dict]:
    code, output = run_cli(root, argv)
    return code, json.loads(output)


def run_cli_text(root: Path, argv: list[str]) -> tuple[int, str]:
    return run_cli(root, argv)


def run_cli(root: Path, argv: list[str]) -> tuple[int, str]:
    stdout = StringIO()
    with change_dir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
        code = main(argv)
    return code, stdout.getvalue()


class change_dir:
    def __init__(self, path: Path):
        self.path = path
        self.previous = None

    def __enter__(self):
        import os

        self.previous = Path.cwd()
        os.chdir(self.path)

    def __exit__(self, exc_type, exc, tb):
        import os

        os.chdir(self.previous)


if __name__ == "__main__":
    unittest.main()

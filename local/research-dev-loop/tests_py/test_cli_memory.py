import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from rdl import integrity, store
from rdl.cli import main
from rdl.session import SessionStore

from rdl_test_support import complete_research_round, create_session


class CliMemoryTests(unittest.TestCase):
    def test_memory_check_reports_gaps_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "memory")
            complete_research_round(session_dir)
            before = snapshot(session_dir)

            code, result = run_cli(root, ["memory", "--check", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "memory")
            self.assertEqual(result["details"]["memory_status"], "needs_attention")
            self.assertEqual(result["details"]["progress_gaps"], ["Active", "Blocked", "Deferred"])
            self.assertIn("Dataset or Workload", result["details"]["factor_gaps"])
            self.assertEqual(result["details"]["deterministic_updates"]["Completed"], 1)
            self.assertEqual(result["next_action"], "rdl memory --write")
            self.assertEqual(snapshot(session_dir), before)

    def test_memory_defaults_to_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_complete_memory_session(root)

            code, result = run_cli(root, ["memory", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["memory_status"], "healthy")

    def test_memory_write_refreshes_summary_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "memory_write")
            complete_research_round(session_dir)

            code, result = run_cli(root, ["memory", "--write", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["memory_status"], "written")
            self.assertEqual(result["details"]["progress_gaps"], ["Active", "Blocked", "Deferred"])
            self.assertIn("Dataset or Workload", result["details"]["factor_gaps"])
            self.assertIn("Record progress memory with rdl progress for sections: Active, Blocked, Deferred.", result["details"]["suggested_actions"])
            self.assertIn(
                "Record factor memory with rdl factors set --section \"Model or Algorithm\" --value <text>.",
                result["details"]["suggested_actions"],
            )
            progress = (session_dir / "progress.md").read_text(encoding="utf-8")
            self.assertIn("<!-- rdl:summary section=Completed start -->", progress)
            self.assertIn("| round-001 | continue | fixture evidence | 001 |", progress)
            ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
            self.assertIn("## Session Summary Refresh", ledger)
            manifest = store.read_json(session_dir / "integrity.json")
            progress_entry = next(entry for entry in manifest["entries"] if entry["path"] == "progress.md")
            self.assertEqual(progress_entry["sha256"], integrity.file_sha256(session_dir / "progress.md"))

    def test_memory_next_action_points_to_progress_helper_for_manual_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "memory_progress_next")

            code, result = run_cli(root, ["memory", "--check", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["next_action"], "rdl progress active|blocked|deferred|none")

    def test_memory_write_is_quiet_when_summary_is_up_to_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "memory_idempotent")
            complete_research_round(session_dir)

            self.assertEqual(run_cli(root, ["memory", "--write", "--json"])[0], 0)
            self.assertEqual(run_cli(root, ["memory", "--write", "--json"])[0], 0)

            progress = (session_dir / "progress.md").read_text(encoding="utf-8")
            ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
            self.assertEqual(progress.count("| round-001 | continue | fixture evidence | 001 |"), 1)
            self.assertEqual(ledger.count("## Session Summary Refresh"), 1)

    def test_memory_check_warns_for_duplicate_open_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_complete_memory_session(root)
            progress_path = session_dir / "progress.md"
            progress_path.write_text(
                progress_path.read_text(encoding="utf-8").replace(
                    "| Question | Owner | Blocking? | Resolution |\n"
                    "|---|---|---|---|\n",
                    "| Question | Owner | Blocking? | Resolution |\n"
                    "|---|---|---|---|\n"
                    "| Which evidence is missing? | team | yes | - |\n"
                    "| which evidence is missing | team | yes | - |\n",
                ),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["memory", "--check", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["memory_status"], "needs_attention")
            self.assertEqual(result["details"]["progress_gaps"], [])
            self.assertEqual(result["details"]["factor_gaps"], [])
            quality_codes = {warning["code"] for warning in result["details"]["quality_warnings"]}
            self.assertIn("duplicate_open_questions", quality_codes)
            self.assertEqual(result["next_action"], "Merge duplicate open questions or mark one resolved.")

    def test_memory_check_warns_for_malformed_progress_table_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_complete_memory_session(root)
            progress_path = session_dir / "progress.md"
            progress_path.write_text(
                progress_path.read_text(encoding="utf-8").replace(
                    "| Question | Owner | Blocking? | Resolution |\n"
                    "|---|---|---|---|\n",
                    "| Question | Owner | Blocking? | Resolution |\n"
                    "|---|---|---|---|\n"
                    "| Is the evidence complete? | team | yes |\n",
                ),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["memory", "--check", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["memory_status"], "needs_attention")
            quality_codes = {warning["code"] for warning in result["details"]["quality_warnings"]}
            self.assertIn("malformed_progress_table_row", quality_codes)

    def test_memory_check_does_not_make_semantic_staleness_judgments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_complete_memory_session(root)
            progress_path = session_dir / "progress.md"
            progress_path.write_text(
                progress_path.read_text(encoding="utf-8").replace(
                    "| no active nonblocking items | research | none | no | - |",
                    "| fixture | research | follow-up capability | no | after review completed |",
                ),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["memory", "--check", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["memory_status"], "healthy")
            quality_codes = {warning["code"] for warning in result["details"]["quality_warnings"]}
            self.assertNotIn("active_item_already_completed", quality_codes)
            self.assertNotIn("active_review_trigger_elapsed", quality_codes)

    def test_memory_write_blocks_for_noncanonical_progress_table_without_partial_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "memory_bad_progress")
            complete_research_round(session_dir)
            progress_path = session_dir / "progress.md"
            progress_path.write_text(
                progress_path.read_text(encoding="utf-8").replace(
                    "| Question | Owner | Blocking? | Resolution |",
                    "| Question | Owner | Blocking | Resolution |",
                ),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())
            before = snapshot(session_dir)

            code, result = run_cli(root, ["memory", "--write", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("unsupported_progress_table", {blocker["code"] for blocker in result["blockers"]})
            self.assertEqual(snapshot(session_dir), before)

    def test_memory_blocks_without_active_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, result = run_cli(Path(tmp), ["memory", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("no_active_session", {blocker["code"] for blocker in result["blockers"]})

    def test_memory_check_reads_specified_inactive_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_complete_memory_session(root)
            mark_closed(session_dir)
            before = snapshot(session_dir)

            code, result = run_cli(root, ["memory", "--check", "--session-id", "memory_complete", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["session_id"], "memory_complete")
            self.assertEqual(result["details"]["memory_status"], "healthy")
            self.assertEqual(snapshot(session_dir), before)

    def test_memory_write_rejects_specified_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_complete_memory_session(root)
            before = snapshot(session_dir)

            code, result = run_cli(root, ["memory", "--write", "--session-path", str(session_dir), "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["blockers"][0]["code"], "session_selector_requires_check")
            self.assertEqual(snapshot(session_dir), before)

    def test_memory_parser_rejects_mutually_exclusive_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "memory_parser")

            code, result = run_cli(root, ["memory", "--check", "--write", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "parser_error")


def create_complete_memory_session(root: Path) -> Path:
    session_dir = create_session(root, "memory_complete")
    complete_research_round(session_dir)
    progress = """# Progress

## Active

| Item | Mode | Claim or Capability | Blocking? | Next Review Trigger |
|---|---|---|---|---|
| no active nonblocking items | research | none | no | - |

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
    run_cli(root, ["memory", "--write", "--json"])
    return session_dir


def snapshot(session_dir: Path) -> dict[str, str]:
    return {
        "progress": (session_dir / "progress.md").read_text(encoding="utf-8"),
        "ledger": (session_dir / "decision-ledger.md").read_text(encoding="utf-8"),
        "integrity": (session_dir / "integrity.json").read_text(encoding="utf-8"),
    }


def mark_closed(session_dir: Path) -> None:
    state_path = session_dir / "state.json"
    state = store.read_json(state_path)
    state["status"] = "closed-positive"
    state["phase"] = "complete"
    store.write_json_atomic(state_path, state)
    integrity.refresh(SessionStore(session_dir.parents[2]).load_session(session_dir))


def run_cli(root: Path, argv: list[str]) -> tuple[int, dict]:
    stdout = StringIO()
    with change_dir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
        code = main(argv)
    return code, json.loads(stdout.getvalue())


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

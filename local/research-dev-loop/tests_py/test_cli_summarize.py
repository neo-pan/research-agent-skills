import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from rdl import integrity, store
from rdl.cli import main
from rdl.memory import prompt_context
from rdl.session import SessionStore

from rdl_test_support import (
    COMPLETE_INTERPRETATION,
    COMPLETE_RESEARCH_EVIDENCE,
    complete_decision,
    complete_research_round,
    complete_review,
    create_session,
)


class CliSummarizeTests(unittest.TestCase):
    def test_summarize_check_reports_updates_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_two_round_session(root)
            before = snapshot(session_dir)

            code, result = run_cli(root, ["summarize", "--check", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "summarize")
            self.assertEqual(result["details"]["summary_status"], "needs_update")
            self.assertEqual(result["details"]["rounds_scanned"], 2)
            self.assertEqual(result["details"]["progress_updates"]["Completed"], 2)
            self.assertEqual(snapshot(session_dir), before)

    def test_summarize_defaults_to_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_two_round_session(root)

            code, result = run_cli(root, ["summarize", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["summary_status"], "needs_update")

    def test_summarize_write_updates_progress_ledger_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_two_round_session(root)

            code, result = run_cli(root, ["summarize", "--write", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["summary_status"], "written")
            progress = (session_dir / "progress.md").read_text(encoding="utf-8")
            self.assertIn("<!-- rdl:summary section=Completed start -->", progress)
            self.assertIn("| round-001 | continue | fixture evidence | 001 |", progress)
            self.assertIn("| round-002 | continue | fixture evidence | 002 |", progress)
            self.assertIn("<!-- rdl:summary section=Open Questions start -->", progress)
            self.assertIn("| later work | unassigned | unknown | - |", progress)
            self.assertIn("<!-- rdl:summary section=Staleness Watch start -->", progress)

            ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
            self.assertIn("<!-- rdl:ledger-summary start -->", ledger)
            self.assertIn("## Session Summary Refresh", ledger)
            self.assertIn("- Through round: 002", ledger)
            manifest = store.read_json(session_dir / "integrity.json")
            progress_entry = next(entry for entry in manifest["entries"] if entry["path"] == "progress.md")
            self.assertEqual(progress_entry["sha256"], integrity.file_sha256(session_dir / "progress.md"))

            context = prompt_context(SessionStore(root).active_session())
            self.assertIn("later work", context.open_questions)
            self.assertIn("fixture prior directions checked", context.directions_tried)
            self.assertIn("possible in round 002", context.staleness_watch)

    def test_summarize_write_keeps_wrapped_missing_evidence_as_one_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_two_round_session(root)
            evidence_file = session_dir / "rounds" / "002" / "evidence.md"
            evidence_file.write_text(
                evidence_file.read_text(encoding="utf-8").replace(
                    "Need a schema inspection.",
                    "Need a schema inspection\nacross wrapped lines.",
                ),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())

            code, _result = run_cli(root, ["summarize", "--write", "--json"])

            self.assertEqual(code, 0)
            progress = (session_dir / "progress.md").read_text(encoding="utf-8")
            self.assertIn("| Need a schema inspection across wrapped lines. | unassigned | unknown | - |", progress)
            self.assertNotIn("| across wrapped lines. | unassigned | unknown | - |", progress)

    def test_prompt_context_ignores_empty_managed_summary_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "summary_markers")
            progress_file = session_dir / "progress.md"
            progress_file.write_text(
                progress_file.read_text(encoding="utf-8").replace(
                    "## Staleness Watch\n\n| Signal | Evidence | Response |\n|---|---|---|\n",
                    "## Staleness Watch\n\n| Signal | Evidence | Response |\n|---|---|---|\n\n"
                    "<!-- rdl:summary section=Staleness Watch start -->\n"
                    "<!-- rdl:summary section=Staleness Watch end -->\n",
                ),
                encoding="utf-8",
            )

            context = prompt_context(SessionStore(root).active_session())

            self.assertEqual(context.staleness_watch, "none recorded")

    def test_summarize_check_is_up_to_date_after_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_two_round_session(root)
            self.assertEqual(run_cli(root, ["summarize", "--write", "--json"])[0], 0)

            code, result = run_cli(root, ["summarize", "--check", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["summary_status"], "up_to_date")

    def test_summarize_write_is_idempotent_for_progress_rows_and_ledger_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_two_round_session(root)

            self.assertEqual(run_cli(root, ["summarize", "--write", "--json"])[0], 0)
            self.assertEqual(run_cli(root, ["summarize", "--write", "--json"])[0], 0)

            progress = (session_dir / "progress.md").read_text(encoding="utf-8")
            self.assertEqual(progress.count("| round-001 | continue | fixture evidence | 001 |"), 1)
            ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
            self.assertEqual(ledger.count("<!-- rdl:ledger-summary start -->"), 1)
            self.assertEqual(ledger.count("## Session Summary Refresh"), 1)

    def test_summarize_round_limits_scanned_rounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_two_round_session(root)

            code, result = run_cli(root, ["summarize", "--write", "--round", "1", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["rounds_scanned"], 1)
            progress = (session_dir / "progress.md").read_text(encoding="utf-8")
            self.assertIn("| round-001 | continue | fixture evidence | 001 |", progress)
            self.assertNotIn("| round-002 | continue | fixture evidence | 002 |", progress)

    def test_summarize_rejects_invalid_round_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_two_round_session(root)
            before = snapshot(session_dir)

            code, result = run_cli(root, ["summarize", "--write", "--round", "3", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertIn("invalid_summary_round", {blocker["code"] for blocker in result["blockers"]})
            self.assertEqual(snapshot(session_dir), before)

    def test_summarize_write_blocks_for_noncanonical_progress_table_without_partial_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_two_round_session(root)
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

            code, result = run_cli(root, ["summarize", "--write", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("unsupported_progress_table", {blocker["code"] for blocker in result["blockers"]})
            self.assertEqual(snapshot(session_dir), before)

    def test_summarize_blocks_without_active_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, result = run_cli(Path(tmp), ["summarize", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("no_active_session", {blocker["code"] for blocker in result["blockers"]})

    def test_summarize_check_reads_specified_inactive_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_two_round_session(root)
            self.assertEqual(run_cli(root, ["summarize", "--write", "--json"])[0], 0)
            mark_closed(session_dir)
            before = snapshot(session_dir)

            code, result = run_cli(root, ["summarize", "--check", "--session-path", str(session_dir), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["session_id"], "summarize")
            self.assertEqual(result["details"]["summary_status"], "up_to_date")
            self.assertEqual(result["next_action"], "none")
            self.assertTrue(result["details"]["terminal"])
            self.assertEqual(result["details"]["terminal_reason"], "session is closed-positive")
            self.assertEqual(snapshot(session_dir), before)

    def test_summarize_write_rejects_specified_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_two_round_session(root)
            before = snapshot(session_dir)

            code, result = run_cli(root, ["summarize", "--write", "--session-id", "summarize", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["blockers"][0]["code"], "session_selector_requires_check")
            self.assertEqual(snapshot(session_dir), before)

    def test_summarize_parser_rejects_mutually_exclusive_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_two_round_session(root)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
                code = main(["summarize", "--check", "--write", "--json"])

            self.assertEqual(code, 1)
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "parser_error")

    def test_summarize_reports_integrity_refresh_failure_after_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_two_round_session(root)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
                with patch("rdl.commands.integrity.refresh", side_effect=ValueError("refresh failed")):
                    code = main(["summarize", "--write", "--json"])

            self.assertEqual(code, 1)
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["blockers"][0]["code"], "integrity_refresh_failed")
            self.assertIn("## Session Summary Refresh", (session_dir / "decision-ledger.md").read_text(encoding="utf-8"))


def create_two_round_session(root: Path) -> Path:
    session_dir = create_session(root, "summarize")
    complete_research_round(session_dir, "continue")
    run_cli(root, ["next", "--json"])
    round_two = session_dir / "rounds" / "002"
    (round_two / "evidence.md").write_text(
        COMPLETE_RESEARCH_EVIDENCE.replace("No blocking missing evidence for this fixture.", "Need a schema inspection."),
        encoding="utf-8",
    )
    (round_two / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
    (round_two / "review.md").write_text(complete_review("continue").replace("Staleness Signal: none", "Staleness Signal: possible"), encoding="utf-8")
    (round_two / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
    integrity.refresh(SessionStore(root).active_session())
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

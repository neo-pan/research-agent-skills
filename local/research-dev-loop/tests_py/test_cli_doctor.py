import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from rdl.cli import main

from rdl_test_support import complete_final_report, complete_research_round, create_session


class CliDoctorTests(unittest.TestCase):
    def test_doctor_json_succeeds_for_healthy_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "doctor")
            self.assertEqual(result["session_id"], "r1")
            self.assertEqual(result["mode"], "research")
            self.assertEqual(result["round"], 1)
            self.assertEqual(result["next_action"], "rdl review")

    def test_doctor_json_blocks_without_active_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout = StringIO()
            with change_dir(Path(tmp)), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blockers"][0]["code"], "no_active_session")

    def test_doctor_json_errors_for_bad_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / ".rdl" / "sessions" / "bad"
            session_dir.mkdir(parents=True)
            (session_dir / "state.json").write_text("{ broken\n", encoding="utf-8")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "invalid_state_json")

    def test_doctor_json_errors_for_integrity_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir)
            (session_dir / "state.json").write_text((session_dir / "state.json").read_text(encoding="utf-8").replace('"phase": "plan"', '"phase": "work"'), encoding="utf-8")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            codes = {blocker["code"] for blocker in result["blockers"]}
            self.assertIn("integrity_violation_cli_owned", codes)

    def test_doctor_json_blocks_for_missing_readiness_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            codes = {blocker["code"] for blocker in result["blockers"]}
            self.assertIn("missing_review", codes)
            self.assertIn("missing_decision", codes)
            blocker_files = {blocker["file"] for blocker in result["blockers"]}
            self.assertIn(str(root / ".rdl" / "sessions" / "r1" / "rounds" / "001" / "review.md"), blocker_files)
            self.assertIn(str(root / ".rdl" / "sessions" / "r1" / "rounds" / "001" / "decision.md"), blocker_files)
            self.assertTrue(blocker_files.issubset(set(result["missing"])))

    def test_doctor_json_blocks_for_close_readiness_progress_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, decision="close-positive")
            (session_dir / "final-report.md").write_text(complete_final_report("positive"), encoding="utf-8")
            (session_dir / "progress.md").write_text(PROGRESS_WITH_BLOCKING_OPEN_QUESTION, encoding="utf-8")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            codes = {blocker["code"] for blocker in result["blockers"]}
            self.assertIn("unresolved_blocking_open_questions", codes)

    def test_unknown_command_remains_unsupported(self):
        with redirect_stderr(StringIO()):
            self.assertEqual(main(["unknown-command"]), 2)


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


PROGRESS_WITH_BLOCKING_OPEN_QUESTION = """# Progress

## Active

none

## Completed

none

## Blocked

none

## Deferred

| Item | Reason | Revisit Trigger |
|---|---|---|

## Open Questions

| Question | Owner | Blocking | Resolution |
|---|---|---|---|
| unresolved risk | team | yes | - |
"""

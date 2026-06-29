import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from rdl import store
from rdl.cli import main

from rdl_test_support import create_session


class CliAbandonTests(unittest.TestCase):
    def test_abandon_json_marks_session_abandoned_and_records_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "abandon_ok")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["abandon", "operator", "stopped", "duplicate", "effort", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "abandon")
            self.assertEqual(result["session_id"], "abandon_ok")
            self.assertEqual(result["mode"], "research")
            self.assertEqual(result["phase"], "complete")
            self.assertEqual(result["round"], 1)
            self.assertEqual(result["next_action"], "abandoned")

            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["status"], "abandoned")
            self.assertEqual(state["phase"], "complete")
            ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
            progress = (session_dir / "progress.md").read_text(encoding="utf-8")
            self.assertIn("## Session Abandoned", ledger)
            self.assertIn("- Reason: operator stopped duplicate effort", ledger)
            self.assertIn("Scientific outcome claimed: none", ledger)
            self.assertIn("## Abandon Record", progress)
            self.assertIn("- Reason: operator stopped duplicate effort", progress)
            manifest = store.read_json(session_dir / "integrity.json")
            self.assertIn("progress.md", {entry["path"] for entry in manifest["entries"]})

    def test_abandon_json_does_not_require_current_round_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "abandon_incomplete")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["abandon", "stopping", "early", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["next_action"], "abandoned")
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "abandoned")
            self.assertFalse((session_dir / "rounds" / "001" / "review.md").exists())
            self.assertFalse((session_dir / "rounds" / "001" / "decision.md").exists())

    def test_abandon_missing_reason_returns_structured_error_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "abandon_missing")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
                self.assertEqual(main(["abandon", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "abandon")
            self.assertEqual(result["blockers"][0]["code"], "missing_abandon_reason")
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")

    def test_abandon_blank_reason_returns_structured_error_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "abandon_blank")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
                self.assertEqual(main(["abandon", "  ", "\t", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "missing_abandon_reason")
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")

    def test_abandon_json_errors_when_integrity_refresh_fails_after_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "abandon_refresh")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                with patch("rdl.cli.integrity.refresh", side_effect=ValueError("refresh failed")):
                    self.assertEqual(main(["abandon", "operator", "stopped", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "abandon")
            self.assertEqual(result["blockers"][0]["code"], "integrity_refresh_failed")
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "abandoned")


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

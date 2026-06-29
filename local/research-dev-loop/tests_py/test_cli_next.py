import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from rdl import integrity, store
from rdl.cli import main
from rdl.session import SessionStore

from rdl_test_support import complete_decision, complete_research_round, complete_review, create_session


class CliNextTests(unittest.TestCase):
    def test_next_json_advances_complete_research_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "next_ok")
            complete_research_round(session_dir, "continue")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "next")
            self.assertEqual(result["session_id"], "next_ok")
            self.assertEqual(result["mode"], "research")
            self.assertEqual(result["phase"], "plan")
            self.assertEqual(result["round"], 2)
            self.assertEqual(result["next_action"], str(session_dir / "rounds" / "002" / "prompt.md"))

            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["round"], 2)
            self.assertEqual(state["phase"], "plan")
            prompt = (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Previous Decision: continue; closes claim; recommended next loop none", prompt)
            ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
            self.assertIn("## Round 1 Decision", ledger)
            self.assertIn("- Next round: 002", ledger)
            manifest = store.read_json(session_dir / "integrity.json")
            entries = {entry["path"]: entry for entry in manifest["entries"]}
            self.assertEqual(entries["rounds/002/prompt.md"]["policy"], "managed_prefix")

    def test_next_json_blocks_for_missing_readiness_records_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["action"], "next")
            codes = {blocker["code"] for blocker in result["blockers"]}
            self.assertIn("missing_review", codes)
            self.assertIn("missing_decision", codes)
            self.assertFalse((session_dir / "rounds" / "002").exists())
            self.assertEqual(store.read_json(session_dir / "state.json")["round"], 1)

    def test_next_json_blocks_for_missing_research_evidence_and_interpretation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            round_dir = session_dir / "rounds" / "001"
            (round_dir / "review.md").write_text(complete_review("continue"), encoding="utf-8")
            (round_dir / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            codes = {blocker["code"] for blocker in result["blockers"]}
            self.assertIn("missing_research_evidence", codes)
            self.assertIn("missing_interpretation", codes)
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_next_json_blocks_for_missing_artifact_citation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")
            decision_path = session_dir / "rounds" / "001" / "decision.md"
            decision_path.write_text(
                decision_path.read_text(encoding="utf-8").replace("Evidence: fixture evidence", "Evidence: ART-1"),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertIn("missing_artifact_citation", {blocker["code"] for blocker in result["blockers"]})
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_next_json_blocks_for_existing_next_round_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")
            next_round = session_dir / "rounds" / "002"
            next_round.mkdir()
            sentinel = next_round / "prompt.md"
            sentinel.write_text(
                "<!-- rdl:managed policy=managed_prefix -->\n# Existing Prompt\n<!-- /rdl:managed -->\n",
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blockers"][0]["code"], "next_round_exists")
            self.assertIn("# Existing Prompt", sentinel.read_text(encoding="utf-8"))
            self.assertEqual(store.read_json(session_dir / "state.json")["round"], 1)

    def test_next_json_errors_when_integrity_refresh_fails_after_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                with patch("rdl.cli.integrity.refresh", side_effect=ValueError("refresh failed")):
                    self.assertEqual(main(["next", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "next")
            self.assertEqual(result["blockers"][0]["code"], "integrity_refresh_failed")
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())

    def test_next_without_json_no_longer_raises_unsupported_parser_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
                self.assertEqual(main(["next"]), 0)

            self.assertIn("ok: next", stdout.getvalue())
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())


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

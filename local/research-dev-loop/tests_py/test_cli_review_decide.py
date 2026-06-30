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

from rdl_test_support import complete_decision, complete_review, create_session


class CliReviewDecideTests(unittest.TestCase):
    def test_review_json_creates_review_from_template_and_refreshes_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_create")

            code, result = run_cli(root, ["review", "--json"])

            review_file = session_dir / "rounds" / "001" / "review.md"
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "review")
            self.assertEqual(result["next_action"], str(review_file))
            self.assertTrue(review_file.is_file())
            self.assertIn("Verdict: PASS | PASS_WITH_NOTES | BLOCKED | INCONCLUSIVE", review_file.read_text(encoding="utf-8"))
            manifest = store.read_json(session_dir / "integrity.json")
            self.assertIn("rounds/001/review.md", {entry["path"] for entry in manifest["entries"]})

    def test_review_json_validates_existing_complete_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_existing")
            review_file = session_dir / "rounds" / "001" / "review.md"
            review_file.write_text(complete_review("continue"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["review", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["next_action"], "rdl decide <decision-type>")

    def test_review_json_blocks_existing_incomplete_review_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_block")
            review_file = session_dir / "rounds" / "001" / "review.md"
            review_file.write_text("# Review\n\nReviewer:\nReview Mode: manual | checklist\n", encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["review", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("missing_review_field", {blocker["code"] for blocker in result["blockers"]})
            self.assertEqual(result["next_action"], "complete review.md")

    def test_review_json_errors_when_integrity_refresh_fails_after_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_refresh")

            with patch("rdl.commands.integrity.refresh", side_effect=ValueError("refresh failed")):
                code, result = run_cli(root, ["review", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "review")
            self.assertEqual(result["blockers"][0]["code"], "integrity_refresh_failed")
            self.assertTrue((session_dir / "rounds" / "001" / "review.md").is_file())

    def test_review_json_errors_when_template_copy_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "review_template")

            with patch("rdl.commands.templates.copy_template", side_effect=FileNotFoundError("missing review template")):
                code, result = run_cli(root, ["review", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "template_write_failed")

    def test_decide_json_creates_decision_from_template_and_refreshes_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "decide_create")

            code, result = run_cli(root, ["decide", "continue", "--json"])

            decision_file = session_dir / "rounds" / "001" / "decision.md"
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "decide")
            self.assertEqual(result["next_action"], str(decision_file))
            text = decision_file.read_text(encoding="utf-8")
            self.assertIn("Decision: continue", text)
            self.assertIn("Closes: claim", text)
            manifest = store.read_json(session_dir / "integrity.json")
            self.assertIn("rounds/001/decision.md", {entry["path"] for entry in manifest["entries"]})

    def test_decide_json_uses_build_closes_for_build_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "decide_build", mode="build")

            code, result = run_cli(root, ["decide", "accept", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            decision_text = (session_dir / "rounds" / "001" / "decision.md").read_text(encoding="utf-8")
            self.assertIn("Decision: accept", decision_text)
            self.assertIn("Closes: capability", decision_text)

    def test_decide_json_validates_existing_complete_matching_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "decide_existing")
            decision_file = session_dir / "rounds" / "001" / "decision.md"
            decision_file.write_text(complete_decision("continue", "claim"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["decide", "continue", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["next_action"], "rdl next")

    def test_decide_json_rejects_unsupported_decision_type(self):
        stdout = StringIO()
        with redirect_stdout(stdout), redirect_stderr(StringIO()):
            code = main(["decide", "ship-it", "--json"])

        result = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["blockers"][0]["code"], "invalid_decision_type")

    def test_decide_json_blocks_existing_decision_type_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "decide_mismatch")
            decision_file = session_dir / "rounds" / "001" / "decision.md"
            decision_file.write_text(complete_decision("continue", "claim"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["decide", "pivot", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("decision_type_mismatch", {blocker["code"] for blocker in result["blockers"]})
            self.assertIn("Decision: continue", decision_file.read_text(encoding="utf-8"))

    def test_decide_json_blocks_existing_incomplete_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "decide_block")
            decision_file = session_dir / "rounds" / "001" / "decision.md"
            decision_file.write_text("# Decision\n\nDecision: continue\nCloses: claim\n", encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["decide", "continue", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("missing_decision_field", {blocker["code"] for blocker in result["blockers"]})
            self.assertEqual(result["next_action"], "complete decision.md")

    def test_decide_json_errors_when_integrity_refresh_fails_after_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "decide_refresh")

            with patch("rdl.commands.integrity.refresh", side_effect=ValueError("refresh failed")):
                code, result = run_cli(root, ["decide", "continue", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "decide")
            self.assertEqual(result["blockers"][0]["code"], "integrity_refresh_failed")
            self.assertTrue((session_dir / "rounds" / "001" / "decision.md").is_file())

    def test_decide_json_errors_when_template_write_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "decide_template")

            with patch("rdl.commands.templates.write_decision", side_effect=FileNotFoundError("missing decision template")):
                code, result = run_cli(root, ["decide", "continue", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "template_write_failed")


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

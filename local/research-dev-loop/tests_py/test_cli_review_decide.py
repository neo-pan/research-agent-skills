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

from rdl_test_support import complete_decision, complete_research_round, complete_review, create_session, set_current_round, write_json


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

    def test_review_pack_json_outputs_agent_context_without_creating_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_cli", profile="checkpoint")
            complete_research_round(session_dir)
            round_two = set_current_round(session_dir, 2)
            (round_two / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
            review_file = round_two / "review.md"

            code, result = run_cli(root, ["review", "--pack", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertFalse(review_file.exists())
            details = result["details"]
            self.assertIn("review_pack", details)
            self.assertIn("gate", details)
            pack = details["review_pack"]
            self.assertEqual(pack["action"], "review")
            self.assertIn("reviewer_task", pack)
            self.assertIn("finding_schema", pack)
            self.assertRegex(pack["subject_digest"], r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(pack["reviewer_task"]["output"]["subject_action"], "echo review_pack.action exactly")
            self.assertEqual(pack["reviewer_task"]["output"]["subject_digest"], "echo review_pack.subject_digest exactly")
            self.assertIn("unchanged_next_smallest_step_across_rounds", {signal["code"] for signal in pack["agent_review_signals"]})
            self.assertIn("rounds/001/evidence.md", {record["path"] for record in pack["records"]})

    def test_review_pack_for_next_uses_next_action_and_filters_expected_review_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_next")
            complete_research_round(session_dir)
            review_file = session_dir / "rounds" / "001" / "review.md"
            review_file.unlink()
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["review", "--pack", "--for", "next", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertFalse(review_file.exists())
            pack = result["details"]["review_pack"]
            self.assertEqual(pack["action"], "next")
            self.assertEqual(pack["reviewer_task"]["action"], "next")
            self.assertIn("next smallest step", "\n".join(pack["reviewer_task"]["questions"]))
            self.assertNotIn("missing_review", {finding["code"] for finding in pack["deterministic_findings"]})
            self.assertIn("missing_review", {finding["code"] for finding in result["details"]["gate"]["findings"]})

    def test_review_pack_for_close_infers_outcome_and_uses_close_action(self):
        for outcome in ("positive", "negative", "inconclusive"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                session_dir = create_session(root, f"review_pack_close_{outcome}")
                round_dir = session_dir / "rounds" / "001"
                (round_dir / "decision.md").write_text(complete_decision(f"close-{outcome}", "claim"), encoding="utf-8")

                code, result = run_cli(root, ["review", "--pack", "--for", "close", "--json"])

                self.assertEqual(code, 0)
                pack = result["details"]["review_pack"]
                self.assertEqual(pack["action"], "close")
                self.assertEqual(pack["reviewer_task"]["action"], "close")
                self.assertIn("close outcome", "\n".join(pack["reviewer_task"]["questions"]))
                self.assertNotIn("missing_review", {finding["code"] for finding in pack["deterministic_findings"]})

    def test_review_pack_for_close_requires_close_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "review_pack_close_missing")

            code, result = run_cli(root, ["review", "--pack", "--for", "close", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "review")
            self.assertEqual(result["blockers"][0]["code"], "missing_close_outcome")
            self.assertNotIn("review_pack", result["details"])

    def test_review_pack_for_doctor_uses_doctor_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "review_pack_doctor", profile="checkpoint")

            code, result = run_cli(root, ["review", "--pack", "--for", "doctor", "--json"])

            self.assertEqual(code, 0)
            pack = result["details"]["review_pack"]
            self.assertEqual(pack["action"], "doctor")
            questions = "\n".join(pack["reviewer_task"]["questions"])
            self.assertNotIn("next smallest step", questions)
            self.assertNotIn("close outcome", questions)

    def test_review_for_requires_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "review_for_requires_pack")

            code, result = run_cli(root, ["review", "--for", "next", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["blockers"][0]["code"], "review_action_requires_pack")

    def test_review_pack_rejects_invalid_review_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "review_for_invalid")

            code, result = run_cli(root, ["review", "--pack", "--for", "publish", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["blockers"][0]["code"], "invalid_review_action")

    def test_review_pack_reports_missing_review_action_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "review_for_missing")

            code, result = run_cli(root, ["review", "--pack", "--for", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["blockers"][0]["code"], "missing_review_action")

    def test_review_pack_json_can_read_specified_session_path_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selected_dir = create_session(root, "review_pack_selected", profile="checkpoint")
            complete_research_round(selected_dir)
            round_two = set_current_round(selected_dir, 2)
            (round_two / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
            mark_inactive(root, selected_dir)
            active_dir = create_session(root, "review_pack_active")
            review_file = round_two / "review.md"
            before_selected = snapshot(selected_dir)
            before_active = snapshot(active_dir)

            code, result = run_cli(root, ["review", "--pack", "--for", "next", "--session-path", str(selected_dir), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["session_id"], "review_pack_selected")
            self.assertFalse(review_file.exists())
            pack = result["details"]["review_pack"]
            self.assertEqual(pack["action"], "next")
            self.assertIn("rounds/001/evidence.md", {record["path"] for record in pack["records"]})
            self.assertEqual(result["next_action"], "none")
            self.assertTrue(result["details"]["terminal"])
            self.assertEqual(result["details"]["terminal_reason"], "session is abandoned")
            self.assertEqual(SessionStore(root).active_session().state.session_id, "review_pack_active")
            self.assertEqual(snapshot(selected_dir), before_selected)
            self.assertEqual(snapshot(active_dir), before_active)

    def test_review_pack_for_next_can_read_specified_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "review_pack_selected_id", profile="checkpoint")

            code, result = run_cli(
                root,
                ["review", "--pack", "--for", "next", "--session-id", "review_pack_selected_id", "--json"],
            )

            self.assertEqual(code, 0)
            self.assertEqual(result["session_id"], "review_pack_selected_id")
            self.assertEqual(result["details"]["review_pack"]["action"], "next")

    def test_review_pack_rejects_unsupported_session_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_bad_schema")
            state_path = session_dir / "state.json"
            state = store.read_json(state_path)
            state["schema_version"] = 2
            write_json(state_path, state)

            code, result = run_cli(root, ["review", "--pack", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "unsupported_schema")
            self.assertNotIn("review_pack", result["details"])

    def test_review_pack_rejects_malformed_integrity_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_bad_integrity")
            (session_dir / "integrity.json").write_text("{broken\n", encoding="utf-8")

            code, result = run_cli(root, ["review", "--pack", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "invalid_integrity_json")
            self.assertNotIn("review_pack", result["details"])

    def test_review_json_rejects_session_selector_without_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "review_selector")

            code, result = run_cli(root, ["review", "--session-id", "review_selector", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "session_selector_requires_pack")

    def test_review_pack_json_rejects_ambiguous_session_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_selector")

            code, result = run_cli(root, ["review", "--pack", "--session-id", "review_selector", "--session-path", str(session_dir), "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "ambiguous_session_selector")

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


def mark_inactive(root: Path, session_dir: Path) -> None:
    state_path = session_dir / "state.json"
    state = store.read_json(state_path)
    state["status"] = "abandoned"
    state["phase"] = "complete"
    store.write_json_atomic(state_path, state)
    integrity.refresh(SessionStore(root).load_session(session_dir))


def snapshot(session_dir: Path) -> dict[str, str]:
    return {
        "state": (session_dir / "state.json").read_text(encoding="utf-8"),
        "integrity": (session_dir / "integrity.json").read_text(encoding="utf-8"),
        "review_exists": str((session_dir / "rounds" / "002" / "review.md").exists()),
    }


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

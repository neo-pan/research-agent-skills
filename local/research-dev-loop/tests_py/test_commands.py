import tempfile
import unittest
from pathlib import Path

from rdl import store
from rdl.commands import CommandIntent, execute

from rdl_test_support import complete_research_round, create_session


class CommandExecutionTests(unittest.TestCase):
    def test_start_creates_session_and_initial_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission = root / "mission.md"
            mission.write_text("# Mission\n\nCommand seam fixture.\n", encoding="utf-8")

            with change_dir(root):
                result = execute(
                    CommandIntent(
                        command="start",
                        mode="research",
                        mission_file=str(mission),
                        session_id="cmd_start",
                    )
                )

            session_dir = root / ".rdl" / "sessions" / "cmd_start"
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.action, "start")
            self.assertEqual(result.session_id, "cmd_start")
            self.assertTrue((session_dir / "state.json").is_file())
            self.assertTrue((session_dir / "rounds" / "001" / "prompt.md").is_file())
            self.assertTrue((session_dir / "integrity.json").is_file())

    def test_review_creates_review_and_refreshes_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "cmd_review")

            with change_dir(root):
                result = execute(CommandIntent(command="review"))

            review_file = session_dir / "rounds" / "001" / "review.md"
            manifest = store.read_json(session_dir / "integrity.json")
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.action, "review")
            self.assertEqual(result.next_action, str(review_file))
            self.assertTrue(review_file.is_file())
            self.assertIn("rounds/001/review.md", {entry["path"] for entry in manifest["entries"]})

    def test_decide_creates_decision_with_expected_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "cmd_decide", mode="build")

            with change_dir(root):
                result = execute(CommandIntent(command="decide", decision_type="accept"))

            decision_file = session_dir / "rounds" / "001" / "decision.md"
            decision = decision_file.read_text(encoding="utf-8")
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.action, "decide")
            self.assertEqual(result.next_action, str(decision_file))
            self.assertIn("Decision: accept", decision)
            self.assertIn("Closes: capability", decision)

    def test_next_advances_complete_research_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "cmd_next")
            complete_research_round(session_dir)

            with change_dir(root):
                result = execute(CommandIntent(command="next"))

            self.assertEqual(result.status, "ok")
            self.assertEqual(result.action, "next")
            self.assertEqual(result.round, 2)
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())

    def test_guard_stop_advances_ready_session_and_records_guard_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "cmd_guard")
            complete_research_round(session_dir)

            with change_dir(root):
                result = execute(
                    CommandIntent(
                        command="guard-stop",
                        guard_session_id="cmd_guard",
                        guard_command_id="cmd-1",
                    )
                )

            state = store.read_json(session_dir / "state.json")
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.action, "guard-stop")
            self.assertEqual(result.round, 2)
            self.assertEqual(state["guard_session_id"], "cmd_guard")
            self.assertEqual(state["last_guard_command_id"], "cmd-1")
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())

    def test_next_blocks_missing_readiness_records_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "cmd_next_blocked")

            with change_dir(root):
                result = execute(CommandIntent(command="next"))

            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.action, "next")
            self.assertIn("missing_review", {blocker.code for blocker in result.blockers})
            self.assertFalse((session_dir / "rounds" / "002").exists())


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

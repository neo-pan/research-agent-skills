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

from rdl_test_support import assert_gate_details_compatible, complete_final_report, complete_research_round, create_session, write_json


class CliGuardStopTests(unittest.TestCase):
    def test_guard_stop_json_allows_without_active_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            code, result = run_guard_stop(root, ["guard-stop", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "guard-stop")
            self.assertEqual(result["round"], 0)
            self.assertEqual(result["next_action"], "allow")

    def test_guard_stop_json_allows_when_guard_session_targets_another_session_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "guard_target")

            code, result = run_guard_stop(root, ["guard-stop", "--guard-session-id", "other", "--guard-command-id", "cmd-1", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["session_id"], "guard_target")
            self.assertEqual(result["next_action"], "allow")
            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["status"], "active")
            self.assertIsNone(state["guard_session_id"])
            self.assertIsNone(state["last_guard_command_id"])

    def test_guard_stop_json_allows_repeated_guard_command_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "guard_repeat")
            state = store.read_json(session_dir / "state.json")
            state["last_guard_command_id"] = "cmd-1"
            write_json(session_dir / "state.json", state)
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_guard_stop(root, ["guard-stop", "--guard-session-id", "guard_repeat", "--guard-command-id", "cmd-1", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["next_action"], "allow")
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_guard_stop_json_closes_close_decisions_and_records_guard_metadata(self):
        for outcome in ("positive", "negative", "inconclusive"):
            with self.subTest(outcome=outcome):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    session_id = f"guard_close_{outcome}"
                    session_dir = close_ready_session(root, session_id, outcome)

                    code, result = run_guard_stop(root, ["guard-stop", "--guard-session-id", session_id, "--guard-command-id", "cmd-1", "--json"])

                    self.assertEqual(code, 0)
                    self.assertEqual(result["status"], "ok")
                    self.assertEqual(result["action"], "guard-stop")
                    self.assertEqual(result["phase"], "complete")
                    self.assertEqual(result["round"], 1)
                    self.assertEqual(result["next_action"], f"closed-{outcome}")
                    assert_gate_details_compatible(self, result["details"]["gate"])
                    state = store.read_json(session_dir / "state.json")
                    self.assertEqual(state["status"], f"closed-{outcome}")
                    self.assertEqual(state["phase"], "complete")
                    self.assertEqual(state["guard_session_id"], session_id)
                    self.assertEqual(state["last_guard_command_id"], "cmd-1")
                    self.assertFalse((session_dir / "rounds" / "002").exists())
                    self.assertIn("## Session Closed", (session_dir / "decision-ledger.md").read_text(encoding="utf-8"))
                    gate_report = store.read_json(session_dir / "rounds" / "001" / "gate-report.json")
                    self.assertEqual(gate_report["action"], "close")
                    self.assertIn("Action: close", (session_dir / "rounds" / "001" / "gate.md").read_text(encoding="utf-8"))

    def test_guard_stop_json_advances_non_close_decision_and_records_guard_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = continue_ready_session(root, "guard_next")

            code, result = run_guard_stop(root, ["guard-stop", "--guard-session-id", "guard_next", "--guard-command-id", "cmd-2", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["phase"], "plan")
            self.assertEqual(result["round"], 2)
            self.assertEqual(result["next_action"], str(session_dir / "rounds" / "002" / "prompt.md"))
            assert_gate_details_compatible(self, result["details"]["gate"])
            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["round"], 2)
            self.assertEqual(state["phase"], "plan")
            self.assertEqual(state["guard_session_id"], "guard_next")
            self.assertEqual(state["last_guard_command_id"], "cmd-2")
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())
            gate_report = store.read_json(session_dir / "rounds" / "001" / "gate-report.json")
            self.assertEqual(gate_report["action"], "advance")
            self.assertIn("Action: advance", (session_dir / "rounds" / "001" / "gate.md").read_text(encoding="utf-8"))

    def test_guard_stop_json_blocks_advance_readiness_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "guard_block")

            code, result = run_guard_stop(root, ["guard-stop", "--guard-session-id", "guard_block", "--guard-command-id", "cmd-1", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["details"]["gate"]["gate_status"], "blocked")
            self.assertIn("missing_review", {blocker["code"] for blocker in result["blockers"]})
            gate_codes = {finding["code"] for finding in result["details"]["gate"]["findings"]}
            self.assertIn("missing_review", gate_codes)
            self.assertEqual(result["next_action"], "block")
            self.assertEqual(store.read_json(session_dir / "state.json")["round"], 1)
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_guard_stop_json_blocks_close_readiness_without_creating_next_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "guard_close_block")
            complete_research_round(session_dir, "close-positive")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_guard_stop(root, ["guard-stop", "--guard-session-id", "guard_close_block", "--guard-command-id", "cmd-1", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("missing_final_report", {blocker["code"] for blocker in result["blockers"]})
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_guard_stop_json_errors_when_integrity_refresh_fails_after_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = continue_ready_session(root, "guard_refresh")

            with patch("rdl.commands.integrity.refresh", side_effect=ValueError("refresh failed")):
                code, result = run_guard_stop(root, ["guard-stop", "--guard-session-id", "guard_refresh", "--guard-command-id", "cmd-1", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "guard-stop")
            self.assertEqual(result["blockers"][0]["code"], "integrity_refresh_failed")
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())

    def test_guard_stop_json_errors_when_gate_report_write_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = continue_ready_session(root, "guard_gate_report_error")

            with patch("rdl.commands.gate_reports.write", side_effect=OSError("disk full")):
                code, result = run_guard_stop(
                    root,
                    ["guard-stop", "--guard-session-id", "guard_gate_report_error", "--guard-command-id", "cmd-1", "--json"],
                )

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "guard-stop")
            self.assertEqual(result["blockers"][0]["code"], "gate_report_write_failed")
            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["round"], 1)
            self.assertEqual(state["phase"], "plan")
            self.assertIsNone(state["guard_session_id"])
            self.assertIsNone(state["last_guard_command_id"])
            self.assertFalse((session_dir / "rounds" / "002").exists())


def run_guard_stop(root: Path, argv: list[str]) -> tuple[int, dict]:
    stdout = StringIO()
    with change_dir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
        code = main(argv)
    return code, json.loads(stdout.getvalue())


def close_ready_session(root: Path, session_id: str, outcome: str = "positive") -> Path:
    session_dir = create_session(root, session_id)
    complete_research_round(session_dir, f"close-{outcome}")
    (session_dir / "final-report.md").write_text(complete_final_report(outcome), encoding="utf-8")
    integrity.refresh(SessionStore(root).active_session())
    return session_dir


def continue_ready_session(root: Path, session_id: str) -> Path:
    session_dir = create_session(root, session_id)
    complete_research_round(session_dir, "continue")
    integrity.refresh(SessionStore(root).active_session())
    return session_dir


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

import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from rdl import integrity, store
from rdl.cli import main
from rdl.session import SessionStore

from rdl_test_support import (
    COMPLETE_BUILD_EVIDENCE,
    COMPLETE_INTENT,
    COMPLETE_INTERPRETATION,
    COMPLETE_RESEARCH_EVIDENCE,
    COMPLETE_WORK,
    complete_decision,
    complete_final_report,
    complete_review,
    refresh_integrity,
    write_json,
)


class MigratedShellE2ETests(unittest.TestCase):
    def test_research_flow_advances_then_closes_through_python_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mission.md").write_text("# Mission\n\nFull research flow.\n", encoding="utf-8")

            code, result = run_cli(root, ["start", "research", "mission.md", "--session-id", "flow", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")

            session_dir = root / ".rdl" / "sessions" / "flow"
            self.assert_session_shape(session_dir, mode="research")

            code, result = run_cli(root, ["review", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["next_action"], str(session_dir / "rounds" / "001" / "review.md"))

            round_one = session_dir / "rounds" / "001"
            (round_one / "review.md").write_text(complete_review("continue"), encoding="utf-8")
            code, result = run_cli(root, ["decide", "continue", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["next_action"], str(round_one / "decision.md"))
            (round_one / "decision.md").write_text(complete_decision_with_next_loop("continue", "claim", "build"), encoding="utf-8")
            (round_one / "evidence.md").write_text(COMPLETE_RESEARCH_EVIDENCE, encoding="utf-8")
            (round_one / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["next", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["round"], 2)
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())
            self.assertIn("recommended next loop build", (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8"))

            round_two = session_dir / "rounds" / "002"
            code, result = run_cli(root, ["review", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["next_action"], str(round_two / "review.md"))
            (round_two / "review.md").write_text(complete_review("close-positive"), encoding="utf-8")
            code, result = run_cli(root, ["decide", "close-positive", "--json"])
            self.assertEqual(code, 0)
            (round_two / "decision.md").write_text(complete_decision("close-positive", "claim"), encoding="utf-8")
            (round_two / "evidence.md").write_text(COMPLETE_RESEARCH_EVIDENCE, encoding="utf-8")
            (round_two / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
            (session_dir / "artifact-manifest.json").write_text(artifact_manifest("E1"), encoding="utf-8")
            (session_dir / "final-report.md").write_text(complete_final_report("positive"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["close", "positive", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["next_action"], "closed-positive")
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "closed-positive")
            self.assertIn("## Session Closed", (session_dir / "decision-ledger.md").read_text(encoding="utf-8"))

    def test_build_flow_requires_verification_then_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plan.md").write_text("# Build Plan\n\nFull build flow.\n", encoding="utf-8")

            code, result = run_cli(root, ["start", "build", "plan.md", "--session-id", "build_flow", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["mode"], "build")
            session_dir = root / ".rdl" / "sessions" / "build_flow"
            self.assert_session_shape(session_dir, mode="build")

            round_one = session_dir / "rounds" / "001"
            (round_one / "review.md").write_text(complete_review("accept"), encoding="utf-8")
            (round_one / "decision.md").write_text(complete_decision("accept", "capability"), encoding="utf-8")
            (round_one / "intent.md").write_text(COMPLETE_INTENT, encoding="utf-8")
            (round_one / "work.md").write_text(COMPLETE_WORK, encoding="utf-8")
            (round_one / "evidence.md").write_text("# Evidence\n\nNo verification recorded.\n", encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["next", "--json"])
            self.assertEqual(code, 2)
            self.assertIn("missing_verification_evidence", blocker_codes(result))
            self.assertFalse((session_dir / "rounds" / "002").exists())

            (round_one / "evidence.md").write_text(COMPLETE_BUILD_EVIDENCE, encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())
            code, result = run_cli(root, ["next", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["round"], 2)
            self.assertIn("Mode: build", (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8"))

    def test_descriptor_ignores_unknown_round_files_but_requires_protected_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mission.md").write_text("# Mission\n\nDescriptor fixture.\n", encoding="utf-8")
            code, _ = run_cli(root, ["start", "research", "mission.md", "--session-id", "descriptor", "--json"])
            self.assertEqual(code, 0)
            session_dir = root / ".rdl" / "sessions" / "descriptor"
            round_dir = session_dir / "rounds" / "001"
            (round_dir / "notes.md").write_text("not protocol state\n", encoding="utf-8")
            (round_dir / "nested").mkdir()
            (round_dir / "nested" / "prompt.md").write_text("# Nested\n", encoding="utf-8")

            code, result = run_cli(root, ["doctor", "--json"])
            self.assertEqual(code, 2)
            files = {blocker.get("file") for blocker in result["blockers"]}
            self.assertNotIn("rounds/001/notes.md", files)
            self.assertNotIn("rounds/001/nested/prompt.md", files)

            integrity_manifest = store.read_json(session_dir / "integrity.json")
            integrity_manifest["entries"] = [
                entry for entry in integrity_manifest["entries"] if entry.get("path") != "rounds/001/prompt.md"
            ]
            write_json(session_dir / "integrity.json", integrity_manifest)

            code, result = run_cli(root, ["doctor", "--json"])
            self.assertEqual(code, 1)
            self.assertIn("missing_integrity_entry", blocker_codes(result))

    def test_start_refuses_corrupt_existing_sessions_before_creating_new_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mission.md").write_text("# Mission\n\nStart guard fixture.\n", encoding="utf-8")
            broken = root / ".rdl" / "sessions" / "broken"
            broken.mkdir(parents=True)

            code, result = run_cli(root, ["start", "research", "mission.md", "--session-id", "new", "--json"])
            self.assertEqual(code, 1)
            self.assertIn("missing_state", blocker_codes(result))
            self.assertFalse((root / ".rdl" / "sessions" / "new").exists())

    def test_guard_stop_records_command_only_and_session_only_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = ready_continue_session(root, "guard_command_only")

            code, result = run_cli(root, ["guard-stop", "--guard-command-id", "cmd-1", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["round"], 2)
            state = store.read_json(session_dir / "state.json")
            self.assertIsNone(state["guard_session_id"])
            self.assertEqual(state["last_guard_command_id"], "cmd-1")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = ready_continue_session(root, "guard_session_only")

            code, result = run_cli(root, ["guard-stop", "--guard-session-id", "guard_session_only", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["round"], 2)
            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["guard_session_id"], "guard_session_only")
            self.assertIsNone(state["last_guard_command_id"])

    def test_close_blocks_template_report_and_missing_reusable_lessons_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "template_report")
            template = Path(__file__).resolve().parents[1] / "templates" / "final-report.md"
            (session_dir / "final-report.md").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["close", "positive", "--json"])
            self.assertEqual(code, 2)
            codes = blocker_codes(result)
            self.assertIn("missing_final_report_section", codes)
            self.assertIn("incomplete_close_checklist", codes)
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "missing_lessons")
            report = session_dir / "final-report.md"
            text = report.read_text(encoding="utf-8")
            report.write_text(text.replace("\n## Reusable Lessons\n\nnone\n", "\n"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["close", "positive", "--json"])
            self.assertEqual(code, 2)
            self.assertIn("missing_final_report_section", blocker_codes(result))
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")

    def assert_session_shape(self, session_dir: Path, mode: str) -> None:
        self.assertTrue((session_dir / "state.json").is_file())
        self.assertTrue((session_dir / "integrity.json").is_file())
        self.assertTrue((session_dir / "mission.md").is_file())
        self.assertTrue((session_dir / "factors.md").is_file())
        self.assertTrue((session_dir / "artifact-manifest.json").is_file())
        self.assertTrue((session_dir / "decision-ledger.md").is_file())
        self.assertTrue((session_dir / "progress.md").is_file())
        self.assertTrue((session_dir / "rounds" / "001" / "prompt.md").is_file())
        state = store.read_json(session_dir / "state.json")
        self.assertEqual(state["mode"], mode)
        self.assertIsNone(state["guard_session_id"])
        self.assertIsNone(state["last_guard_command_id"])
        entries = store.read_json(session_dir / "integrity.json")["entries"]
        policies = {entry["path"]: entry["policy"] for entry in entries}
        self.assertEqual(policies["state.json"], "cli_owned")
        self.assertEqual(policies["decision-ledger.md"], "append_only")
        self.assertEqual(policies["rounds/001/prompt.md"], "managed_prefix")
        self.assertEqual(policies["mission.md"], "human_owned")


def ready_continue_session(root: Path, session_id: str) -> Path:
    (root / "mission.md").write_text("# Mission\n\nGuard fixture.\n", encoding="utf-8")
    code, _ = run_cli(root, ["start", "research", "mission.md", "--session-id", session_id, "--json"])
    assert code == 0
    session_dir = root / ".rdl" / "sessions" / session_id
    round_dir = session_dir / "rounds" / "001"
    (round_dir / "review.md").write_text(complete_review("continue"), encoding="utf-8")
    (round_dir / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
    (round_dir / "evidence.md").write_text(COMPLETE_RESEARCH_EVIDENCE, encoding="utf-8")
    (round_dir / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
    integrity.refresh(SessionStore(root).active_session())
    return session_dir


def close_ready_session(root: Path, session_id: str) -> Path:
    session_dir = ready_continue_session(root, session_id)
    round_dir = session_dir / "rounds" / "001"
    (round_dir / "review.md").write_text(complete_review("close-positive"), encoding="utf-8")
    (round_dir / "decision.md").write_text(complete_decision("close-positive", "claim"), encoding="utf-8")
    (session_dir / "artifact-manifest.json").write_text(artifact_manifest("E1"), encoding="utf-8")
    (session_dir / "final-report.md").write_text(complete_final_report("positive"), encoding="utf-8")
    integrity.refresh(SessionStore(root).active_session())
    return session_dir


def artifact_manifest(artifact_id: str) -> str:
    return json.dumps(
        {
            "artifacts": [
                {
                    "id": artifact_id,
                    "kind": "log",
                    "path": "artifacts/check.log",
                    "round": 1,
                    "description": "Fixture evidence artifact",
                }
            ]
        },
        indent=2,
    ) + "\n"


def complete_decision_with_next_loop(decision: str, closes: str, next_loop: str) -> str:
    return complete_decision(decision, closes).replace(
        "Recommended next loop: none",
        f"Recommended next loop: {next_loop}",
    )


def blocker_codes(result: dict) -> set[str]:
    return {blocker["code"] for blocker in result.get("blockers", [])}


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

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


class CliStartStatusTests(unittest.TestCase):
    def test_start_research_json_creates_session_files_prompt_state_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission = root / "mission-source.md"
            mission.write_text("# Mission\n\nResearch this claim.\n", encoding="utf-8")

            code, result = run_cli(root, ["start", "research", str(mission), "--session-id", "start_research", "--json"])

            session_dir = root / ".rdl" / "sessions" / "start_research"
            prompt_file = session_dir / "rounds" / "001" / "prompt.md"
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "start")
            self.assertEqual(result["session_id"], "start_research")
            self.assertEqual(result["mode"], "research")
            self.assertEqual(result["profile"], "full-review")
            self.assertEqual(result["phase"], "plan")
            self.assertEqual(result["round"], 1)
            self.assertEqual(result["next_action"], str(prompt_file))
            self.assertEqual((session_dir / "mission.md").read_text(encoding="utf-8"), mission.read_text(encoding="utf-8"))
            for name in ("factors.md", "artifact-manifest.json", "decision-ledger.md", "progress.md"):
                self.assertTrue((session_dir / name).is_file(), name)
            prompt = prompt_file.read_text(encoding="utf-8")
            self.assertIn("Mode: research", prompt)
            self.assertIn("Profile: full-review", prompt)
            self.assertIn("Objective: mission-source.md", prompt)
            self.assertIn("Previous Decision: none", prompt)
            self.assertIn("Required Files: prompt.md, evidence.md, interpretation.md, review.md, decision.md", prompt)
            self.assertIn("Expected Exit Decision: claim decision with evidence and uncertainty", prompt)
            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["schema_version"], 1)
            self.assertEqual(state["session_id"], "start_research")
            self.assertEqual(state["mode"], "research")
            self.assertEqual(state["profile"], "full-review")
            self.assertEqual(state["phase"], "plan")
            self.assertEqual(state["round"], 1)
            self.assertEqual(state["status"], "active")
            self.assertEqual(state["mission_file"], "mission.md")
            self.assertIsNone(state["guard_session_id"])
            self.assertIsNone(state["last_guard_command_id"])
            self.assertEqual(state["prompt_objective"], "mission-source.md")
            self.assertTrue(state["created_at_utc"])
            self.assertEqual(state["created_at_utc"], state["updated_at_utc"])
            manifest = store.read_json(session_dir / "integrity.json")
            self.assertEqual(manifest["session_id"], "start_research")
            self.assertIn("state.json", {entry["path"] for entry in manifest["entries"]})
            self.assertIn("rounds/001/prompt.md", {entry["path"] for entry in manifest["entries"]})

    def test_start_build_json_creates_build_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "build-plan.md"
            plan.write_text("# Plan\n\nBuild this capability.\n", encoding="utf-8")

            code, result = run_cli(root, ["start", "build", str(plan), "--session-id", "start_build", "--json"])

            prompt = (root / ".rdl" / "sessions" / "start_build" / "rounds" / "001" / "prompt.md").read_text(encoding="utf-8")
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["mode"], "build")
            self.assertIn("Mode: build", prompt)
            self.assertIn("Required Files: prompt.md, intent.md, work.md, evidence.md, review.md, decision.md", prompt)
            self.assertIn("Expected Exit Decision: capability decision with verification evidence", prompt)

    def test_start_json_accepts_checkpoint_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission = root / "mission.md"
            mission.write_text("# Mission\n\nCheckpoint this claim.\n", encoding="utf-8")

            code, result = run_cli(root, ["start", "research", str(mission), "--profile", "checkpoint", "--session-id", "start_checkpoint", "--json"])

            session_dir = root / ".rdl" / "sessions" / "start_checkpoint"
            self.assertEqual(code, 0)
            self.assertEqual(result["profile"], "checkpoint")
            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["profile"], "checkpoint")
            prompt = (session_dir / "rounds" / "001" / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Profile: checkpoint", prompt)
            self.assertIn("Required Files: prompt.md, evidence.md, decision.md", prompt)

    def test_start_json_rejects_profile_not_supported_by_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission = root / "mission.md"
            mission.write_text("# Mission\n", encoding="utf-8")

            code, result = run_cli(root, ["start", "research", str(mission), "--profile", "build-update", "--session-id", "bad_profile", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "invalid_profile_for_mode")
            self.assertFalse((root / ".rdl" / "sessions" / "bad_profile").exists())

    def test_start_json_blocks_when_active_session_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "existing")
            mission = root / "mission.md"
            mission.write_text("# Mission\n", encoding="utf-8")

            code, result = run_cli(root, ["start", "research", str(mission), "--session-id", "new_session", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blockers"][0]["code"], "active_session_exists")
            self.assertFalse((root / ".rdl" / "sessions" / "new_session").exists())

    def test_start_json_rejects_invalid_session_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission = root / "mission.md"
            mission.write_text("# Mission\n", encoding="utf-8")

            code, result = run_cli(root, ["start", "research", str(mission), "--session-id", "bad/id", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "invalid_session_id")
            self.assertFalse((root / ".rdl" / "sessions" / "bad").exists())

    def test_start_json_rejects_dot_only_session_ids_without_parent_writes(self):
        for session_id, forbidden_files in (
            (".", (".rdl/sessions/state.json", ".rdl/sessions/rounds")),
            ("..", (".rdl/state.json", ".rdl/rounds")),
        ):
            with self.subTest(session_id=session_id):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    mission = root / "mission.md"
                    mission.write_text("# Mission\n", encoding="utf-8")

                    code, result = run_cli(root, ["start", "research", str(mission), "--session-id", session_id, "--json"])

                    self.assertEqual(code, 1)
                    self.assertEqual(result["status"], "error")
                    self.assertEqual(result["blockers"][0]["code"], "invalid_session_id")
                    for relative in forbidden_files:
                        self.assertFalse((root / relative).exists(), relative)

    def test_start_json_blocks_existing_session_id_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            existing = root / ".rdl" / "sessions" / "old"
            existing.mkdir(parents=True)
            (existing / "sentinel.txt").write_text("keep\n", encoding="utf-8")
            mission = root / "mission.md"
            mission.write_text("# Mission\n", encoding="utf-8")

            code, result = run_cli(root, ["start", "research", str(mission), "--session-id", "old", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blockers"][0]["code"], "session_already_exists")
            self.assertEqual((existing / "sentinel.txt").read_text(encoding="utf-8"), "keep\n")

    def test_start_json_errors_for_missing_mission_file_without_partial_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.md"

            code, result = run_cli(root, ["start", "research", str(missing), "--session-id", "missing_mission", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "missing_mission_file")
            self.assertFalse((root / ".rdl" / "sessions" / "missing_mission").exists())

    def test_start_json_errors_when_integrity_refresh_fails_without_final_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission = root / "mission.md"
            mission.write_text("# Mission\n", encoding="utf-8")

            with patch("rdl.session.integrity.refresh", side_effect=ValueError("refresh failed")):
                code, result = run_cli(root, ["start", "research", str(mission), "--session-id", "refresh_fail", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "integrity_refresh_failed")
            self.assertFalse((root / ".rdl" / "sessions" / "refresh_fail").exists())

    def test_status_json_returns_active_session_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "status_active", mode="build")

            code, result = run_cli(root, ["status", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "status")
            self.assertEqual(result["session_id"], "status_active")
            self.assertEqual(result["mode"], "build")
            self.assertEqual(result["profile"], "full-review")
            self.assertEqual(result["phase"], "plan")
            self.assertEqual(result["round"], 1)
            self.assertEqual(result["next_action"], "active")

    def test_status_json_ignores_malformed_integrity_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "status_bad_integrity")
            (session_dir / "integrity.json").write_text("{ broken\n", encoding="utf-8")

            code, result = run_cli(root, ["status", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["session_id"], "status_bad_integrity")
            self.assertEqual(result["next_action"], "active")

    def test_status_json_ignores_missing_non_state_protocol_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "status_missing_progress")
            (session_dir / "progress.md").unlink()

            code, result = run_cli(root, ["status", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["session_id"], "status_missing_progress")
            self.assertEqual(result["next_action"], "active")

    def test_status_json_errors_for_invalid_state_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / ".rdl" / "sessions" / "bad_state"
            session_dir.mkdir(parents=True)
            (session_dir / "state.json").write_text("{ broken\n", encoding="utf-8")

            code, result = run_cli(root, ["status", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "invalid_state_json")

    def test_status_json_errors_for_invalid_state_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "bad_values")
            state = store.read_json(session_dir / "state.json")
            state["schema_version"] = 2
            state["status"] = "bad"
            write_json(session_dir / "state.json", state)

            code, result = run_cli(root, ["status", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            codes = {blocker["code"] for blocker in result["blockers"]}
            self.assertIn("unsupported_schema", codes)
            self.assertIn("invalid_status", codes)

    def test_status_json_errors_for_missing_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / ".rdl" / "sessions" / "missing_state"
            session_dir.mkdir(parents=True)

            code, result = run_cli(root, ["status", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "missing_state")

    def test_status_json_errors_for_multiple_active_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "active_one")
            create_session(root, "active_two")

            code, result = run_cli(root, ["status", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "multiple_active_sessions")

    def test_status_json_without_active_session_points_to_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, result = run_cli(Path(tmp), ["status", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "status")
            self.assertEqual(result["round"], 0)
            self.assertEqual(result["next_action"], "rdl start research <mission.md>")


def run_cli(root: Path, argv: list[str]) -> tuple[int, dict]:
    stdout = StringIO()
    with change_dir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
        code = main(argv)
    return code, json.loads(stdout.getvalue())


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


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

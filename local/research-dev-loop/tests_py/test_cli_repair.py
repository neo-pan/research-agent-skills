import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from rdl import integrity, store
from rdl.cli import main
from rdl.session import SessionStore

from rdl_test_support import complete_research_round, create_session, refresh_integrity, set_current_round


class CliRepairTests(unittest.TestCase):
    def test_repair_json_refreshes_stale_integrity_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_stale")
            with (session_dir / "decision-ledger.md").open("a", encoding="utf-8") as fh:
                fh.write("\n## Appended\n\nSafe append.\n")

            code, result = run_cli(root, ["repair", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "repair")
            self.assertEqual(result["next_action"], "integrity.json")
            refreshed = store.read_json(session_dir / "integrity.json")
            ledger_entry = next(entry for entry in refreshed["entries"] if entry["path"] == "decision-ledger.md")
            self.assertEqual(ledger_entry["size"], (session_dir / "decision-ledger.md").stat().st_size)

    def test_repair_json_removes_stale_lock_and_reports_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_lock")
            (session_dir / ".lock").write_text("pid=999999\n", encoding="utf-8")

            code, result = run_cli(root, ["repair", "--json"])

            self.assertEqual(code, 0)
            self.assertFalse((session_dir / ".lock").exists())
            self.assertEqual(result["next_action"], ".lock,integrity.json")

    def test_repair_json_regenerates_missing_initial_prompt_when_metadata_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_prompt")
            (session_dir / "rounds" / "001" / "prompt.md").unlink()

            code, result = run_cli(root, ["repair", "--json"])

            prompt = session_dir / "rounds" / "001" / "prompt.md"
            self.assertEqual(code, 0)
            self.assertTrue(prompt.is_file())
            self.assertIn("Objective: mission.md", prompt.read_text(encoding="utf-8"))
            self.assertEqual(result["next_action"], "rounds/001/prompt.md,integrity.json")

    def test_repair_json_blocks_missing_initial_prompt_without_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_prompt_metadata")
            state = store.read_json(session_dir / "state.json")
            state["prompt_objective"] = ""
            write_json(session_dir / "state.json", state)
            integrity.refresh(SessionStore(root).load_session(session_dir))
            (session_dir / "rounds" / "001" / "prompt.md").unlink()

            code, result = run_cli(root, ["repair", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("missing_prompt_metadata", {blocker["code"] for blocker in result["blockers"]})

    def test_repair_json_blocks_missing_active_round_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_round")
            remove_tree(session_dir / "rounds" / "001")

            code, result = run_cli(root, ["repair", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("unsafe_missing_round_dir", {blocker["code"] for blocker in result["blockers"]})

    def test_repair_json_errors_for_cli_owned_state_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_state")
            state = store.read_json(session_dir / "state.json")
            state["phase"] = "work"
            write_json(session_dir / "state.json", state)

            code, result = run_cli(root, ["repair", "--json"])

            self.assertEqual(code, 1)
            self.assertIn("unsafe_cli_owned_change", {blocker["code"] for blocker in result["blockers"]})

    def test_repair_json_errors_for_append_only_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_ledger")
            (session_dir / "decision-ledger.md").write_text("# Rewritten Ledger\n", encoding="utf-8")

            code, result = run_cli(root, ["repair", "--json"])

            self.assertEqual(code, 1)
            self.assertIn("unsafe_append_only_change", {blocker["code"] for blocker in result["blockers"]})

    def test_repair_json_errors_for_managed_prompt_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_managed")
            prompt = session_dir / "rounds" / "001" / "prompt.md"
            prompt.write_text(prompt.read_text(encoding="utf-8").replace("Mode: research", "Mode: build"), encoding="utf-8")

            code, result = run_cli(root, ["repair", "--json"])

            self.assertEqual(code, 1)
            self.assertIn("unsafe_managed_prefix_change", {blocker["code"] for blocker in result["blockers"]})

    def test_repair_json_errors_for_human_owned_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_human")
            (session_dir / "mission.md").write_text("# Mission\n\nChanged.\n", encoding="utf-8")

            code, result = run_cli(root, ["repair", "--json"])

            self.assertEqual(code, 1)
            self.assertIn("unsafe_human_owned_change", {blocker["code"] for blocker in result["blockers"]})

    def test_repair_json_refuses_missing_human_owned_manifest_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_human_entry")
            manifest = store.read_json(session_dir / "integrity.json")
            manifest["entries"] = [entry for entry in manifest["entries"] if entry["path"] != "mission.md"]
            write_json(session_dir / "integrity.json", manifest)

            code, result = run_cli(root, ["repair", "--json"])

            self.assertEqual(code, 1)
            self.assertIn("missing_integrity_entry", {blocker["code"] for blocker in result["blockers"]})
            self.assertIn("mission.md", {blocker["file"] for blocker in result["blockers"]})

    def test_repair_json_accepts_state_recorded_custom_mission_manifest_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_custom_mission")
            state = store.read_json(session_dir / "state.json")
            state["mission_file"] = "custom-mission.md"
            write_json(session_dir / "state.json", state)
            (session_dir / "mission.md").unlink()
            (session_dir / "custom-mission.md").write_text("# Mission\n\nCustom.\n", encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["repair", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertNotIn("unsafe_integrity_entry", {blocker["code"] for blocker in result["blockers"]})

    def test_repair_json_applies_state_derived_history_lesson_for_missing_prior_round_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_history")
            complete_research_round(session_dir)
            set_current_round(session_dir, 2)
            (session_dir / "rounds" / "001" / "evidence.md").unlink()
            manifest = store.read_json(session_dir / "integrity.json")
            manifest["entries"] = [entry for entry in manifest["entries"] if entry["path"] != "rounds/001/evidence.md"]
            write_json(session_dir / "integrity.json", manifest)

            code, result = run_cli(root, ["repair", "--json"])

            self.assertEqual(code, 1)
            self.assertIn("unsafe_missing_protocol_file", {blocker["code"] for blocker in result["blockers"]})
            self.assertIn("rounds/001/evidence.md", {blocker["file"] for blocker in result["blockers"]})

    def test_repair_json_errors_when_integrity_manifest_is_unusable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "repair_unusable")
            (session_dir / "integrity.json").write_text("{ broken\n", encoding="utf-8")

            code, result = run_cli(root, ["repair", "--json"])

            self.assertEqual(code, 1)
            self.assertIn("unsafe_integrity_manifest", {blocker["code"] for blocker in result["blockers"]})


def run_cli(root: Path, argv: list[str]) -> tuple[int, dict]:
    stdout = StringIO()
    with change_dir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
        code = main(argv)
    return code, json.loads(stdout.getvalue())


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def remove_tree(path: Path) -> None:
    import shutil

    shutil.rmtree(path)


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

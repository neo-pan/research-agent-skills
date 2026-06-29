import tempfile
import unittest
import os
import subprocess
import hashlib
from pathlib import Path

from rdl import store
from rdl.model import SessionMode, SessionPhase, SessionStatus
from rdl.session import SessionState, SessionStore

from rdl_test_support import create_session, refresh_integrity, write_json


class StoreSessionTests(unittest.TestCase):
    def test_store_reads_and_writes_structured_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            store.write_json_atomic(path, {"round": 1, "mode": "research"})
            self.assertEqual(store.read_json(path), {"round": 1, "mode": "research"})

    def test_active_session_loads_state_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root)

            session = SessionStore(root).active_session()
            self.assertIsNotNone(session)
            self.assertEqual(session.state.session_id, "r1")
            self.assertEqual(session.state.mode, SessionMode.RESEARCH)
            self.assertEqual(session.state.phase, SessionPhase.PLAN)
            self.assertEqual(session.state.status, SessionStatus.ACTIVE)
            self.assertEqual(session.round_dir().name, "001")
            self.assertEqual(session.path("rounds/001/prompt.md"), session.round_dir() / "prompt.md")

    def test_session_audit_accepts_structurally_complete_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            session = SessionStore(Path(tmp)).active_session()

            audit = session.audit()
            self.assertEqual(audit.errors, ())
            self.assertEqual(audit.blockers, ())
            self.assertEqual(session_dir, session.root)

    def test_integrity_json_malformed_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            (session_dir / "integrity.json").write_text("{ broken\n", encoding="utf-8")

            audit = SessionStore(Path(tmp)).active_session().audit()
            self.assertIn("invalid_integrity_json", {blocker.code for blocker in audit.errors})

    def test_integrity_hash_mismatch_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            (session_dir / "state.json").write_text((session_dir / "state.json").read_text(encoding="utf-8").replace('"phase": "plan"', '"phase": "work"'), encoding="utf-8")

            audit = SessionStore(Path(tmp)).active_session().audit()
            self.assertIn("integrity_violation_cli_owned", {blocker.code for blocker in audit.errors})

    def test_integrity_managed_prefix_hash_matches_bash_newline_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            manifest = store.read_json(session_dir / "integrity.json")
            prompt_path = session_dir / "rounds" / "001" / "prompt.md"
            text = prompt_path.read_text(encoding="utf-8")
            end = "<!-- /rdl:managed -->"
            managed = text[: text.index(end) + len(end)]
            managed_with_closing_newline = managed + "\n"
            for entry in manifest["entries"]:
                if entry["path"] == "rounds/001/prompt.md":
                    entry["managed_sha256"] = hashlib.sha256(managed_with_closing_newline.encode("utf-8")).hexdigest()
                    break
            write_json(session_dir / "integrity.json", manifest)

            audit = SessionStore(Path(tmp)).active_session().audit()
            self.assertEqual(audit.errors, ())

    def test_integrity_missing_protected_entry_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            manifest = store.read_json(session_dir / "integrity.json")
            manifest["entries"] = [entry for entry in manifest["entries"] if entry["path"] != "state.json"]
            write_json(session_dir / "integrity.json", manifest)

            audit = SessionStore(Path(tmp)).active_session().audit()
            self.assertIn("missing_integrity_entry", {blocker.code for blocker in audit.errors})

    def test_integrity_expected_set_includes_round_files_above_state_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            extra_round = session_dir / "rounds" / "002"
            extra_round.mkdir()
            (extra_round / "prompt.md").write_text(
                "<!-- rdl:managed policy=managed_prefix -->\n# Prompt\n\nRound: 2\n<!-- /rdl:managed -->\n",
                encoding="utf-8",
            )

            audit = SessionStore(Path(tmp)).active_session().audit()
            self.assertIn("missing_integrity_entry", {blocker.code for blocker in audit.errors})

    def test_no_active_session_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(SessionStore(Path(tmp)).active_session())

    def test_multiple_active_sessions_raise_store_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "r1")
            create_session(root, "r2")

            with self.assertRaises(ValueError):
                SessionStore(root).active_session()

    def test_malformed_session_is_not_hidden_by_active_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "active")
            bad_dir = root / ".rdl" / "sessions" / "bad"
            bad_dir.mkdir(parents=True)
            (bad_dir / "state.json").write_text("{ broken\n", encoding="utf-8")

            session = SessionStore(root).active_session()
            self.assertEqual(session.root.name, "bad")
            self.assertEqual([blocker.code for blocker in session.audit().errors], ["invalid_state_json"])

    def test_bad_state_json_loads_error_session_for_doctor_reporting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / ".rdl" / "sessions" / "bad"
            session_dir.mkdir(parents=True)
            (session_dir / "state.json").write_text("{ broken\n", encoding="utf-8")

            session = SessionStore(root).active_session()
            audit = session.audit()
            self.assertEqual([blocker.code for blocker in audit.errors], ["invalid_state_json"])

    def test_invalid_closed_state_metadata_is_not_hidden_by_active_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "active")
            bad_dir = create_session(root, "closed_bad")
            state = store.read_json(bad_dir / "state.json")
            state["schema_version"] = 2
            state["session_id"] = ""
            state["status"] = "closed-positive"
            state["mission_file"] = ""
            write_json(bad_dir / "state.json", state)

            session = SessionStore(root).active_session()
            self.assertEqual(session.root.name, "closed_bad")
            codes = {blocker.code for blocker in session.audit().errors}
            self.assertIn("unsupported_schema", codes)
            self.assertIn("missing_session_id", codes)
            self.assertIn("missing_mission_file_field", codes)

    def test_invalid_state_values_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            state_path = session_dir / "state.json"
            state_path.write_text(
                '{"schema_version":2,"session_id":"","mode":"deploy","phase":"bad","round":0,"status":"bad","mission_file":""}\n',
                encoding="utf-8",
            )

            audit = SessionStore(Path(tmp)).active_session().audit()
            codes = {blocker.code for blocker in audit.errors}
            self.assertIn("unsupported_schema", codes)
            self.assertIn("missing_session_id", codes)
            self.assertIn("invalid_mode", codes)
            self.assertIn("invalid_phase", codes)
            self.assertIn("invalid_round", codes)
            self.assertIn("invalid_status", codes)
            self.assertIn("missing_mission_file_field", codes)

    def test_missing_state_mode_phase_status_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            state = store.read_json(session_dir / "state.json")
            del state["mode"]
            del state["phase"]
            del state["status"]
            write_json(session_dir / "state.json", state)
            refresh_integrity(session_dir)

            audit = SessionStore(Path(tmp)).active_session().audit()
            codes = {blocker.code for blocker in audit.errors}
            self.assertIn("invalid_mode", codes)
            self.assertIn("invalid_phase", codes)
            self.assertIn("invalid_status", codes)

    def test_non_string_session_id_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            state = store.read_json(session_dir / "state.json")
            state["session_id"] = 123
            write_json(session_dir / "state.json", state)
            refresh_integrity(session_dir)

            audit = SessionStore(Path(tmp)).active_session().audit()
            self.assertIn("missing_session_id", {blocker.code for blocker in audit.errors})

    def test_non_string_mission_file_is_reported_as_state_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            state = store.read_json(session_dir / "state.json")
            state["mission_file"] = 123
            write_json(session_dir / "state.json", state)

            audit = SessionStore(Path(tmp)).active_session().audit()
            self.assertIn("missing_mission_file_field", {blocker.code for blocker in audit.errors})

    def test_live_session_lock_blocks_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            process = subprocess.Popen(["sleep", "30"])
            try:
                (session_dir / ".lock").write_text(f"pid={process.pid}\naction=test\ncreated_at_utc=2026-06-29T00:00:00Z\n", encoding="utf-8")

                audit = SessionStore(Path(tmp)).active_session().audit()
                self.assertIn("session_locked", {blocker.code for blocker in audit.blockers})
            finally:
                process.terminate()
                process.wait()

    def test_stale_session_lock_blocks_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            (session_dir / ".lock").write_text("pid=99999999\naction=test\ncreated_at_utc=2026-06-29T00:00:00Z\n", encoding="utf-8")

            audit = SessionStore(Path(tmp)).active_session().audit()
            self.assertIn("stale_lock", {blocker.code for blocker in audit.blockers})

    def test_missing_required_files_and_round_prompt_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            (session_dir / "progress.md").unlink()
            (session_dir / "rounds" / "001" / "prompt.md").unlink()

            audit = SessionStore(Path(tmp)).active_session().audit()
            codes = [blocker.code for blocker in audit.blockers]
            self.assertIn("missing_required_file", codes)
            self.assertIn("missing_prompt", codes)

    def test_artifact_manifest_must_be_object_with_artifacts_array(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            (session_dir / "artifact-manifest.json").write_text("[]\n", encoding="utf-8")
            refresh_integrity(session_dir)

            audit = SessionStore(Path(tmp)).active_session().audit()
            self.assertIn("invalid_artifact_manifest", {blocker.code for blocker in audit.blockers})

    def test_artifact_entries_require_string_fields_and_positive_round(self):
        invalid_artifacts = [
            {"id": 123, "kind": "log", "round": 1, "description": "evidence", "path": "artifact.txt"},
            {"id": "A-1", "kind": 123, "round": 1, "description": "evidence", "path": "artifact.txt"},
            {"id": "A-1", "kind": "log", "round": 1, "description": 123, "path": "artifact.txt"},
            {"id": "A-1", "kind": "log", "round": 1, "description": "evidence", "path": 123},
            {"id": "A-1", "kind": "log", "round": 0, "description": "evidence", "path": "artifact.txt"},
        ]
        for artifact in invalid_artifacts:
            with self.subTest(artifact=artifact):
                with tempfile.TemporaryDirectory() as tmp:
                    session_dir = create_session(Path(tmp))
                    write_json(session_dir / "artifact-manifest.json", {"artifacts": [artifact]})
                    refresh_integrity(session_dir)

                    audit = SessionStore(Path(tmp)).active_session().audit()
                    self.assertIn("invalid_artifact_entry", {blocker.code for blocker in audit.blockers})

    def test_session_state_requires_object(self):
        with self.assertRaises(ValueError):
            SessionState.from_json([])


if __name__ == "__main__":
    unittest.main()

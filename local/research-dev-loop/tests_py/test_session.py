import tempfile
import unittest
from pathlib import Path

from rdl import store
from rdl.model import SessionMode, SessionPhase, SessionStatus
from rdl.session import SessionState, SessionStore

from rdl_test_support import create_session


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

    def test_bad_state_json_loads_error_session_for_doctor_reporting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / ".rdl" / "sessions" / "bad"
            session_dir.mkdir(parents=True)
            (session_dir / "state.json").write_text("{ broken\n", encoding="utf-8")

            session = SessionStore(root).active_session()
            audit = session.audit()
            self.assertEqual([blocker.code for blocker in audit.errors], ["invalid_state_json"])

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

    def test_missing_required_files_and_round_prompt_are_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp))
            (session_dir / "progress.md").unlink()
            (session_dir / "rounds" / "001" / "prompt.md").unlink()

            audit = SessionStore(Path(tmp)).active_session().audit()
            codes = [blocker.code for blocker in audit.blockers]
            self.assertIn("missing_required_file", codes)
            self.assertIn("missing_prompt", codes)

    def test_session_state_requires_object(self):
        with self.assertRaises(ValueError):
            SessionState.from_json([])


if __name__ == "__main__":
    unittest.main()

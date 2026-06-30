import tempfile
import unittest
from pathlib import Path

from rdl import safety
from rdl.session import SessionStore

from rdl_test_support import create_session


class SafetyTests(unittest.TestCase):
    def test_audit_matches_session_audit_for_valid_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = SessionStore(root).load_session(create_session(root, "safe_valid"))

            self.assertEqual(safety.audit(session), session.audit())
            self.assertTrue(safety.audit(session).ok)

    def test_audit_reports_malformed_integrity_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "safe_bad_integrity")
            (session_dir / "integrity.json").write_text("{ broken\n", encoding="utf-8")
            session = SessionStore(root).load_session(session_dir)

            audit = safety.audit(session)

            self.assertIn("invalid_integrity_json", {blocker.code for blocker in audit.errors})
            self.assertEqual(audit.blockers, ())

    def test_audit_reports_stale_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "safe_stale_lock")
            (session_dir / ".lock").write_text(
                "pid=99999999\naction=test\ncreated_at_utc=2026-06-29T00:00:00Z\n",
                encoding="utf-8",
            )
            session = SessionStore(root).load_session(session_dir)

            audit = safety.audit(session)

            self.assertIn("stale_lock", {blocker.code for blocker in audit.blockers})
            self.assertEqual(audit.errors, ())

    def test_state_errors_reports_invalid_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "safe_bad_round")
            state_path = session_dir / "state.json"
            state_text = state_path.read_text(encoding="utf-8").replace('"round": 1', '"round": 0')
            state_path.write_text(state_text, encoding="utf-8")
            session = SessionStore(root).load_session(session_dir)

            errors = safety.state_errors(session)

            self.assertIn("invalid_round", {blocker.code for blocker in errors})


if __name__ == "__main__":
    unittest.main()

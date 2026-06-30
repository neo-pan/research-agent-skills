import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rdl import safety, store
from rdl.session import SessionStore

from rdl_test_support import complete_research_round, create_session, set_current_round, write_json


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

    def test_state_errors_returns_missing_state_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / ".rdl" / "sessions" / "missing_state"
            session_dir.mkdir(parents=True)
            session = SessionStore(root).load_session(session_dir)

            errors = safety.state_errors(session)

            self.assertEqual({blocker.code for blocker in errors}, {"missing_state"})

    def test_state_errors_returns_invalid_state_json_load_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = root / ".rdl" / "sessions" / "invalid_state"
            session_dir.mkdir(parents=True)
            (session_dir / "state.json").write_text("{ broken\n", encoding="utf-8")
            session = SessionStore(root).load_session(session_dir)

            errors = safety.state_errors(session)

            self.assertEqual({blocker.code for blocker in errors}, {"invalid_state_json"})

    def test_repair_scope_assessment_accepts_valid_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = SessionStore(root).load_session(create_session(root, "safe_repair_valid"))

            assessment = safety.assess_repair_scope(session)

            self.assertTrue(assessment.ok)

    def test_repair_scope_assessment_rejects_unusable_integrity_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "safe_repair_unusable")
            (session_dir / "integrity.json").write_text("{ broken\n", encoding="utf-8")
            session = SessionStore(root).load_session(session_dir)

            assessment = safety.assess_repair_scope(session)

            self.assertIn("unsafe_integrity_manifest", {blocker.code for blocker in assessment.errors})

    def test_repair_scope_assessment_rejects_cli_owned_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "safe_repair_state")
            state = store.read_json(session_dir / "state.json")
            state["phase"] = "work"
            write_json(session_dir / "state.json", state)
            session = SessionStore(root).load_session(session_dir)

            assessment = safety.assess_repair_scope(session)

            self.assertIn("unsafe_cli_owned_change", {blocker.code for blocker in assessment.errors})

    def test_repair_scope_assessment_rejects_append_only_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "safe_repair_ledger")
            (session_dir / "decision-ledger.md").write_text("# Rewritten Ledger\n", encoding="utf-8")
            session = SessionStore(root).load_session(session_dir)

            assessment = safety.assess_repair_scope(session)

            self.assertIn("unsafe_append_only_change", {blocker.code for blocker in assessment.errors})

    def test_repair_scope_assessment_rejects_managed_prompt_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "safe_repair_prompt")
            prompt = session_dir / "rounds" / "001" / "prompt.md"
            prompt.write_text(prompt.read_text(encoding="utf-8").replace("Mode: research", "Mode: build"), encoding="utf-8")
            session = SessionStore(root).load_session(session_dir)

            assessment = safety.assess_repair_scope(session)

            self.assertIn("unsafe_managed_prefix_change", {blocker.code for blocker in assessment.errors})

    def test_repair_scope_assessment_rejects_human_owned_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "safe_repair_human")
            (session_dir / "mission.md").write_text("# Mission\n\nChanged.\n", encoding="utf-8")
            session = SessionStore(root).load_session(session_dir)

            assessment = safety.assess_repair_scope(session)

            self.assertIn("unsafe_human_owned_change", {blocker.code for blocker in assessment.errors})

    def test_repair_scope_assessment_derives_missing_prior_round_files_from_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "safe_repair_history")
            complete_research_round(session_dir)
            set_current_round(session_dir, 2)
            (session_dir / "rounds" / "001" / "evidence.md").unlink()
            manifest = store.read_json(session_dir / "integrity.json")
            manifest["entries"] = [entry for entry in manifest["entries"] if entry["path"] != "rounds/001/evidence.md"]
            write_json(session_dir / "integrity.json", manifest)
            session = SessionStore(root).load_session(session_dir)

            assessment = safety.assess_repair_scope(session)

            self.assertIn("unsafe_missing_protocol_file", {blocker.code for blocker in assessment.errors})
            self.assertIn("rounds/001/evidence.md", {blocker.file for blocker in assessment.errors})

    def test_lock_blocker_reports_live_and_stale_locks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock = root / ".lock"
            process = subprocess.Popen(["sleep", "10"])
            try:
                lock.write_text(f"pid={process.pid}\naction=test\ncreated_at_utc=2026-06-29T00:00:00Z\n", encoding="utf-8")
                live = safety.lock_blocker(lock)
            finally:
                process.terminate()
                process.wait(timeout=5)

            lock.write_text("pid=99999999\naction=test\ncreated_at_utc=2026-06-29T00:00:00Z\n", encoding="utf-8")
            stale = safety.lock_blocker(lock)

            self.assertIsNotNone(live)
            self.assertEqual(live.code, "session_locked")
            self.assertIsNotNone(stale)
            self.assertEqual(stale.code, "stale_lock")

    def test_permission_denied_lock_liveness_preserves_audit_and_repair_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / ".lock"
            lock.write_text("pid=123456\naction=test\ncreated_at_utc=2026-06-29T00:00:00Z\n", encoding="utf-8")

            with patch("rdl.safety.os.kill", side_effect=PermissionError):
                audit_blocker = safety.lock_blocker(lock)
                repair_blocker = safety.repair_lock_blocker(lock)

            self.assertIsNotNone(audit_blocker)
            self.assertEqual(audit_blocker.code, "stale_lock")
            self.assertIsNotNone(repair_blocker)
            self.assertEqual(repair_blocker.code, "session_locked")


if __name__ == "__main__":
    unittest.main()

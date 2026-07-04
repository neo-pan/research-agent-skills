import tempfile
import unittest
from pathlib import Path

from rdl import gate
from rdl import integrity
from rdl.session import SessionStore

from rdl_test_support import complete_decision, complete_research_round, create_session


class GateTests(unittest.TestCase):
    def test_doctor_gate_blocks_for_missing_round_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "gate_missing")
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertEqual(report.status, "blocked")
            codes = {blocker.code for blocker in report.blockers}
            self.assertIn("missing_review", codes)
            self.assertIn("missing_decision", codes)
            self.assertEqual(report.details["gate_status"], "blocked")
            categories = {finding["category"] for finding in report.details["findings"]}
            self.assertIn("protocol", categories)

    def test_doctor_gate_reports_memory_and_summary_warnings_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_warnings")
            complete_research_round(session_dir)
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertFalse(report.blockers)
            self.assertEqual(report.status, "needs_attention")
            self.assertIn("summary_needs_update", report.warnings)
            self.assertIn("session_memory_needs_attention", report.warnings)
            self.assertEqual(report.details["summary"]["summary_status"], "needs_update")
            self.assertEqual(report.details["memory"]["memory_status"], "needs_attention")

    def test_doctor_gate_warns_when_round_content_is_ahead_of_state_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_state")
            complete_research_round(session_dir)
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertIn("round_content_ahead_of_state_phase", report.warnings)
            findings = {finding["code"]: finding for finding in report.details["findings"]}
            self.assertEqual(findings["round_content_ahead_of_state_phase"]["category"], "state")

    def test_state_content_warning_requires_valid_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_state_invalid")
            complete_research_round(session_dir)
            decision_file = session_dir / "rounds" / "001" / "decision.md"
            decision_file.write_text(
                decision_file.read_text(encoding="utf-8").replace("Recommended next loop: none", "Recommended next loop: unsupported"),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertNotIn("round_content_ahead_of_state_phase", report.warnings)

    def test_close_gate_includes_advance_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "gate_close_missing")
            session = SessionStore(root).active_session()

            report = gate.run(session, "close", outcome="positive")

            self.assertEqual(report.status, "blocked")
            codes = {blocker.code for blocker in report.blockers}
            self.assertIn("missing_review", codes)
            self.assertIn("missing_decision", codes)

    def test_close_gate_rejects_invalid_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "gate_close_invalid")
            session = SessionStore(root).active_session()

            report = gate.run(session, "close", outcome="stale")

            self.assertEqual(report.status, "blocked")
            self.assertEqual([blocker.code for blocker in report.blockers], ["invalid_close_outcome"])

    def test_close_gate_blocks_mismatched_close_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_close_mismatch")
            complete_research_round(session_dir, decision="continue")
            decision_file = session_dir / "rounds" / "001" / "decision.md"
            decision_file.write_text(complete_decision("continue", "claim"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())
            session = SessionStore(root).active_session()

            report = gate.run(session, "close", outcome="positive")

            self.assertEqual(report.status, "blocked")
            self.assertIn("invalid_close_decision", {blocker.code for blocker in report.blockers})


if __name__ == "__main__":
    unittest.main()

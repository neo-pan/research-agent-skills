import tempfile
import unittest
from pathlib import Path

from rdl import readiness
from rdl.session import SessionStore

from rdl_test_support import complete_build_round, complete_research_round, create_session


class ReadinessTests(unittest.TestCase):
    def test_complete_research_round_is_doctor_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), mode="research")
            complete_research_round(session_dir)

            session = SessionStore(Path(tmp)).active_session()
            self.assertEqual(readiness.check(session, "doctor-current"), [])

    def test_research_round_requires_evidence_and_interpretation(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), mode="research")
            complete_research_round(session_dir)
            (session_dir / "rounds" / "001" / "interpretation.md").write_text("# Interpretation\n\n", encoding="utf-8")

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current")}
            self.assertIn("missing_interpretation", codes)

    def test_complete_build_round_is_doctor_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), session_id="b1", mode="build")
            complete_build_round(session_dir)

            self.assertEqual(readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current"), [])

    def test_build_round_requires_verification_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), session_id="b1", mode="build")
            complete_build_round(session_dir, verification=False)

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current")}
            self.assertIn("missing_verification_evidence", codes)

    def test_document_validators_are_used_for_review_and_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), mode="research")
            complete_research_round(session_dir)
            (session_dir / "rounds" / "001" / "review.md").unlink()

            codes = [blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current")]
            self.assertIn("missing_review", codes)

    def test_unknown_readiness_plan_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), mode="research")
            complete_research_round(session_dir)

            blockers = readiness.check(SessionStore(Path(tmp)).active_session(), "unknown-plan")
            self.assertEqual([blocker.code for blocker in blockers], ["invalid_readiness_plan"])


if __name__ == "__main__":
    unittest.main()

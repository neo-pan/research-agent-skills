import hashlib
import json
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

    def test_gate_blocks_for_missing_local_artifact_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_artifact_missing")
            complete_research_round(session_dir)
            _write_artifact_manifest(
                session_dir,
                [
                    {
                        "id": "EV-MISSING",
                        "kind": "log",
                        "round": 1,
                        "description": "missing local artifact",
                        "path": "artifacts/missing.log",
                    }
                ],
            )
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertEqual(report.status, "blocked")
            self.assertIn("missing_artifact_path", {blocker.code for blocker in report.blockers})
            findings = {finding["code"]: finding for finding in report.details["findings"]}
            self.assertEqual(findings["missing_artifact_path"]["category"], "artifact")
            self.assertEqual(report.details["artifact"]["artifact_status"], "blocked")

    def test_gate_blocks_for_local_artifact_size_and_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_artifact_mismatch")
            complete_research_round(session_dir)
            artifact_path = root / "artifacts" / "evidence.log"
            artifact_path.parent.mkdir()
            artifact_path.write_text("actual evidence\n", encoding="utf-8")
            _write_artifact_manifest(
                session_dir,
                [
                    {
                        "id": "EV-SIZE",
                        "kind": "log",
                        "round": 1,
                        "description": "size mismatch",
                        "path": "artifacts/evidence.log",
                        "size": artifact_path.stat().st_size + 1,
                    },
                    {
                        "id": "EV-HASH",
                        "kind": "log",
                        "round": 1,
                        "description": "hash mismatch",
                        "path": "artifacts/evidence.log",
                        "sha256": hashlib.sha256(b"different evidence\n").hexdigest(),
                    },
                ],
            )
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            codes = {blocker.code for blocker in report.blockers}
            self.assertIn("artifact_size_mismatch", codes)
            self.assertIn("artifact_sha256_mismatch", codes)

    def test_gate_ignores_remote_url_artifact_reachability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_remote_artifact")
            complete_research_round(session_dir)
            _write_artifact_manifest(
                session_dir,
                [
                    {
                        "id": "EV-REMOTE",
                        "kind": "report",
                        "round": 1,
                        "description": "remote artifact",
                        "url": "https://example.invalid/artifact.json",
                    }
                ],
            )
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertNotIn("missing_artifact_path", {blocker.code for blocker in report.blockers})
            self.assertEqual(report.details["artifact"]["remote_artifacts"], 1)

    def test_gate_warns_for_duplicate_local_path_with_different_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_duplicate_artifact_path")
            complete_research_round(session_dir)
            artifact_path = root / "artifacts" / "shared.log"
            artifact_path.parent.mkdir()
            artifact_path.write_text("actual evidence\n", encoding="utf-8")
            _write_artifact_manifest(
                session_dir,
                [
                    {
                        "id": "EV-OLD",
                        "kind": "log",
                        "round": 1,
                        "description": "old snapshot",
                        "path": "artifacts/shared.log",
                        "sha256": hashlib.sha256(b"old evidence\n").hexdigest(),
                    },
                    {
                        "id": "EV-NEW",
                        "kind": "log",
                        "round": 1,
                        "description": "new snapshot",
                        "path": "artifacts/shared.log",
                        "sha256": hashlib.sha256(b"new evidence\n").hexdigest(),
                    },
                ],
            )
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertIn("duplicate_artifact_path_hashes", report.warnings)
            self.assertNotIn("artifact_sha256_mismatch", {blocker.code for blocker in report.blockers})
            findings = {finding["code"]: finding for finding in report.details["findings"]}
            self.assertEqual(findings["duplicate_artifact_path_hashes"]["category"], "artifact")


def _write_artifact_manifest(session_dir: Path, artifacts: list[dict[str, object]]) -> None:
    (session_dir / "artifact-manifest.json").write_text(json.dumps({"artifacts": artifacts}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

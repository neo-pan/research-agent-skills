import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from rdl import gate
from rdl import integrity
from rdl.session import SessionStore

from rdl_test_support import complete_decision, complete_final_report, complete_research_round, create_session, set_current_round


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

    def test_gate_warns_for_duplicate_open_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_duplicate_questions")
            complete_research_round(session_dir)
            progress_path = session_dir / "progress.md"
            progress_path.write_text(
                progress_path.read_text(encoding="utf-8").replace(
                    "## Open Questions\n\n",
                    "## Open Questions\n\n"
                    "| Question | Owner | Blocking? | Resolution |\n"
                    "|---|---|---|---|\n"
                    "| Which evidence is missing? | team | yes | - |\n"
                    "| which evidence is missing | team | yes | - |\n\n",
                ),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertIn("duplicate_open_questions", report.warnings)
            findings = {finding["code"]: finding for finding in report.details["findings"]}
            self.assertEqual(findings["duplicate_open_questions"]["category"], "memory")
            quality_codes = {warning["code"] for warning in report.details["memory"]["quality_warnings"]}
            self.assertIn("duplicate_open_questions", quality_codes)

    def test_gate_exposes_memory_quality_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_memory_quality")
            complete_research_round(session_dir)
            progress_path = session_dir / "progress.md"
            progress_path.write_text(
                progress_path.read_text(encoding="utf-8").replace(
                    "| Question | Owner | Blocking? | Resolution |\n"
                    "|---|---|---|---|\n",
                    "| Question | Owner | Blocking? | Resolution |\n"
                    "|---|---|---|---|\n"
                    "| Which evidence is missing? | team | yes |\n",
                ),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertIn("malformed_progress_table_row", report.warnings)
            findings = {finding["code"]: finding for finding in report.details["findings"]}
            self.assertEqual(findings["malformed_progress_table_row"]["category"], "memory")
            quality_codes = {warning["code"] for warning in report.details["memory"]["quality_warnings"]}
            self.assertIn("malformed_progress_table_row", quality_codes)

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

    def test_full_review_gate_blocks_missing_semantic_review_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "gate_semantic_missing")
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertIn("missing_semantic_review", {blocker.code for blocker in report.blockers})
            self.assertEqual(report.details["semantic"]["semantic_status"], "blocked")
            self.assertTrue(report.details["semantic"]["required"])

    def test_gate_includes_recorded_semantic_review_without_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_semantic_recorded")
            complete_research_round(session_dir)
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            semantic = report.details["semantic"]
            self.assertEqual(semantic["semantic_status"], "ok")
            self.assertEqual(semantic["adapter"], "manual")
            self.assertEqual(semantic["reviewed_artifacts"], ["prompt", "evidence", "decision"])
            findings = {finding["code"]: finding for finding in report.details["findings"]}
            self.assertEqual(findings["semantic_review_recorded"]["category"], "semantic")
            self.assertEqual(findings["semantic_review_recorded"]["severity"], "note")
            self.assertNotIn("semantic_review_recorded", report.warnings)

    def test_lightweight_gate_does_not_require_semantic_review_without_review_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "gate_semantic_checkpoint", profile="checkpoint")
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertFalse(report.details["semantic"]["required"])
            self.assertNotIn("missing_semantic_review", {blocker.code for blocker in report.blockers})

    def test_close_gate_requires_semantic_review_even_for_lightweight_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_semantic_close_checkpoint", profile="checkpoint")
            round_dir = session_dir / "rounds" / "001"
            (round_dir / "decision.md").write_text(complete_decision("close-positive", "claim"), encoding="utf-8")
            (session_dir / "final-report.md").write_text(complete_final_report("positive"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())
            session = SessionStore(root).active_session()

            report = gate.run(session, "close", outcome="positive")

            self.assertTrue(report.details["semantic"]["required"])
            self.assertIn("missing_semantic_review", {blocker.code for blocker in report.blockers})

    def test_handoff_gate_does_not_require_semantic_review_for_full_review_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root, "gate_semantic_handoff")
            session = SessionStore(root).active_session()

            report = gate.run(session, "handoff")

            self.assertFalse(report.details["semantic"]["required"])
            self.assertNotIn("missing_semantic_review", {blocker.code for blocker in report.blockers})

    def test_repeated_next_step_requires_semantic_review_for_lightweight_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_semantic_repeated_checkpoint", profile="checkpoint")
            complete_research_round(session_dir, "continue")
            round_two = set_current_round(session_dir, 2)
            (round_two / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertIn("unchanged_next_smallest_step_across_rounds", report.warnings)
            self.assertTrue(report.details["semantic"]["required"])
            self.assertIn("missing_semantic_review", {blocker.code for blocker in report.blockers})

    def test_semantic_review_staleness_risk_warns_without_parser_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_semantic_stale")
            complete_research_round(session_dir)
            review_file = session_dir / "rounds" / "001" / "review.md"
            review_file.write_text(
                review_file.read_text(encoding="utf-8").replace("Fresh Evidence: yes", "Fresh Evidence: no"),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertIn("semantic_review_staleness_risk", report.warnings)
            findings = {finding["code"]: finding for finding in report.details["findings"]}
            self.assertEqual(findings["semantic_review_staleness_risk"]["category"], "semantic")

    def test_close_inconclusive_allows_semantic_evidence_gap_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_semantic_inconclusive")
            complete_research_round(session_dir, decision="close-inconclusive")
            (session_dir / "final-report.md").write_text(complete_final_report("inconclusive"), encoding="utf-8")
            review_file = session_dir / "rounds" / "001" / "review.md"
            review_file.write_text(
                review_file.read_text(encoding="utf-8")
                .replace("Verdict: PASS", "Verdict: INCONCLUSIVE")
                .replace("Blocking Evidence Gaps: none", "Blocking Evidence Gaps: missing decisive baseline"),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())
            session = SessionStore(root).active_session()

            report = gate.run(session, "close", outcome="inconclusive")

            self.assertNotIn("semantic_review_evidence_gaps", {blocker.code for blocker in report.blockers})
            self.assertIn("semantic_review_evidence_gaps", report.warnings)
            findings = {finding["code"]: finding for finding in report.details["findings"]}
            self.assertEqual(findings["semantic_review_evidence_gaps"]["severity"], "warning")

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

    def test_gate_warns_for_malformed_optional_artifact_integrity_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "gate_artifact_metadata")
            complete_research_round(session_dir)
            artifact_path = root / "artifacts" / "metadata.log"
            artifact_path.parent.mkdir()
            artifact_path.write_text("actual evidence\n", encoding="utf-8")
            _write_artifact_manifest(
                session_dir,
                [
                    {
                        "id": "EV-BAD-META",
                        "kind": "log",
                        "round": 1,
                        "description": "bad metadata",
                        "path": "artifacts/metadata.log",
                        "size": "large",
                        "sha256": "not-a-digest",
                    }
                ],
            )
            session = SessionStore(root).active_session()

            report = gate.run(session, "doctor")

            self.assertIn("invalid_artifact_size_metadata", report.warnings)
            self.assertIn("invalid_artifact_sha256_metadata", report.warnings)
            self.assertNotIn("artifact_size_mismatch", {blocker.code for blocker in report.blockers})
            self.assertNotIn("artifact_sha256_mismatch", {blocker.code for blocker in report.blockers})
            findings = {finding["code"]: finding for finding in report.details["findings"]}
            self.assertEqual(findings["invalid_artifact_size_metadata"]["category"], "artifact")
            self.assertEqual(report.details["artifact"]["artifact_status"], "needs_attention")


def _write_artifact_manifest(session_dir: Path, artifacts: list[dict[str, object]]) -> None:
    (session_dir / "artifact-manifest.json").write_text(json.dumps({"artifacts": artifacts}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

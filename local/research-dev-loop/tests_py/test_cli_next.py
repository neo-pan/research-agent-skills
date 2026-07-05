import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from rdl import integrity, store
from rdl.cli import main
from rdl.session import SessionStore

from rdl_test_support import (
    COMPLETE_BUILD_EVIDENCE,
    COMPLETE_INTERPRETATION,
    COMPLETE_INTENT,
    COMPLETE_RESEARCH_EVIDENCE,
    COMPLETE_WORK,
    assert_gate_details_compatible,
    complete_decision,
    complete_research_round,
    complete_review,
    create_session,
)


class CliNextTests(unittest.TestCase):
    def test_next_json_advances_complete_research_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "next_ok")
            complete_research_round(session_dir, "continue")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "next")
            self.assertEqual(result["session_id"], "next_ok")
            self.assertEqual(result["mode"], "research")
            self.assertEqual(result["phase"], "plan")
            self.assertEqual(result["round"], 2)
            self.assertEqual(result["next_action"], str(session_dir / "rounds" / "002" / "prompt.md"))
            self.assertNotIn("summary_needs_update", result["warnings"])
            assert_gate_details_compatible(self, result["details"]["gate"])
            self.assertEqual(result["details"]["gate"]["summary"]["summary_status"], "up_to_date")

            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["round"], 2)
            self.assertEqual(state["phase"], "plan")
            prompt = (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Previous Decision: continue; closes claim; recommended next loop none", prompt)
            progress = (session_dir / "progress.md").read_text(encoding="utf-8")
            self.assertIn("<!-- rdl:summary section=Completed start -->", progress)
            self.assertIn("| round-001 | continue | fixture evidence | 001 |", progress)
            ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
            self.assertIn("## Session Summary Refresh", ledger)
            self.assertIn("## Round 1 Decision", ledger)
            self.assertIn("- Next round: 002", ledger)
            manifest = store.read_json(session_dir / "integrity.json")
            entries = {entry["path"]: entry for entry in manifest["entries"]}
            self.assertEqual(entries["progress.md"]["sha256"], integrity.file_sha256(session_dir / "progress.md"))
            self.assertEqual(entries["rounds/001/gate-report.json"]["policy"], "cli_owned")
            self.assertEqual(entries["rounds/001/gate.md"]["policy"], "cli_owned")
            self.assertEqual(entries["rounds/002/prompt.md"]["policy"], "managed_prefix")
            gate_report = store.read_json(session_dir / "rounds" / "001" / "gate-report.json")
            self.assertEqual(gate_report["action"], "advance")
            self.assertEqual(gate_report["status"], "needs_attention")
            self.assertEqual(gate_report["details"]["semantic"]["adapter"], "manual")
            self.assertIn("semantic_review_recorded", {finding["code"] for finding in gate_report["details"]["findings"]})
            self.assertIn("Status: needs_attention", (session_dir / "rounds" / "001" / "gate.md").read_text(encoding="utf-8"))

    def test_next_json_can_transition_to_build_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "next_mode")
            complete_research_round(session_dir, "continue")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--mode", "build", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["mode"], "build")
            self.assertEqual(store.read_json(session_dir / "state.json")["mode"], "build")
            prompt = (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Mode: build", prompt)
            self.assertIn("Required Files: prompt.md, intent.md, work.md, evidence.md, review.md, decision.md", prompt)
            ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
            self.assertIn("- Next mode: build", ledger)

    def test_next_json_can_set_next_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "next_profile")
            complete_research_round(session_dir, "continue")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--profile", "checkpoint", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["profile"], "checkpoint")
            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["profile"], "checkpoint")
            prompt = (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Profile: checkpoint", prompt)
            self.assertIn("Required Files: prompt.md, evidence.md, decision.md", prompt)
            ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
            self.assertIn("- Profile: full-review", ledger)
            self.assertIn("- Next profile: checkpoint", ledger)

    def test_next_json_can_transition_mode_and_profile_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "next_build_update")
            complete_research_round(session_dir, "continue")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--mode", "build", "--profile", "build-update", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["mode"], "build")
            self.assertEqual(result["profile"], "build-update")
            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["mode"], "build")
            self.assertEqual(state["profile"], "build-update")
            prompt = (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Mode: build", prompt)
            self.assertIn("Profile: build-update", prompt)
            self.assertIn("Required Files: prompt.md, intent.md, work.md, evidence.md, decision.md", prompt)

    def test_next_json_blocks_incompatible_inherited_profile_for_new_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "incompatible_profile", mode="build", profile="build-update")
            round_dir = session_dir / "rounds" / "001"
            (round_dir / "intent.md").write_text(COMPLETE_INTENT, encoding="utf-8")
            (round_dir / "work.md").write_text(COMPLETE_WORK, encoding="utf-8")
            (round_dir / "evidence.md").write_text(COMPLETE_BUILD_EVIDENCE, encoding="utf-8")
            (round_dir / "decision.md").write_text(complete_decision("accept", "capability"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--mode", "research", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "blocked")
            self.assertIn("invalid_profile_for_mode", {blocker["code"] for blocker in result["blockers"]})
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_next_json_recommended_loop_mismatch_warns_without_switching_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "next_warn")
            complete_research_round(session_dir, "continue")
            decision_path = session_dir / "rounds" / "001" / "decision.md"
            decision_path.write_text(
                decision_path.read_text(encoding="utf-8").replace("Recommended next loop: none", "Recommended next loop: build"),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["mode"], "research")
            self.assertIn("recommended_next_loop_differs_from_next_mode", result["warnings"])
            self.assertIn("Mode: research", (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8"))

    def test_next_json_errors_when_gate_report_write_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "next_gate_report_error")
            complete_research_round(session_dir, "continue")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout), patch("rdl.commands.gate_reports.write", side_effect=OSError("disk full")):
                self.assertEqual(main(["next", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "gate_report_write_failed")
            self.assertEqual(store.read_json(session_dir / "state.json")["round"], 1)
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_next_json_rejects_invalid_mode_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "bad_next_mode")
            complete_research_round(session_dir, "continue")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--mode", "deploy", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertIn("invalid_mode", {blocker["code"] for blocker in result["blockers"]})
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_next_json_rejects_invalid_profile_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "bad_next_profile")
            complete_research_round(session_dir, "continue")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--profile", "audit", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertIn("invalid_profile", {blocker["code"] for blocker in result["blockers"]})
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_doctor_json_warns_for_empty_session_memory_after_multiple_rounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "memory_warn")
            complete_research_round(session_dir, "continue")
            with change_dir(root), redirect_stdout(StringIO()):
                self.assertEqual(main(["next", "--json"]), 0)
            round_two = session_dir / "rounds" / "002"
            (round_two / "review.md").write_text(complete_review("continue"), encoding="utf-8")
            (round_two / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
            (round_two / "evidence.md").write_text(COMPLETE_RESEARCH_EVIDENCE, encoding="utf-8")
            (round_two / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())
            with change_dir(root), redirect_stdout(StringIO()):
                self.assertEqual(main(["next", "--json"]), 0)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertIn("empty_factors_memory_after_first_round", result["warnings"])
            self.assertIn("session_memory_needs_attention", result["warnings"])

    def test_recent_rounds_without_artifacts_are_agent_review_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "artifact_warn")
            complete_research_round(session_dir, "continue")
            with change_dir(root), redirect_stdout(StringIO()):
                self.assertEqual(main(["next", "--json"]), 0)
            round_two = session_dir / "rounds" / "002"
            (round_two / "review.md").write_text(complete_review("continue"), encoding="utf-8")
            (round_two / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
            (round_two / "evidence.md").write_text(COMPLETE_RESEARCH_EVIDENCE, encoding="utf-8")
            (round_two / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())
            with change_dir(root), redirect_stdout(StringIO()):
                self.assertEqual(main(["next", "--json"]), 0)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--json"]), 2)
            doctor_result = json.loads(stdout.getvalue())
            self.assertNotIn("no_recent_artifacts_after_multiple_rounds", doctor_result["warnings"])

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 2)
            next_result = json.loads(stdout.getvalue())
            self.assertNotIn("no_recent_artifacts_after_multiple_rounds", next_result["warnings"])

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["review", "--pack", "--json"]), 0)
            review_result = json.loads(stdout.getvalue())
            signal_codes = {signal["code"] for signal in review_result["details"]["review_pack"]["agent_review_signals"]}
            self.assertIn("no_recent_artifacts_after_multiple_rounds", signal_codes)

    def test_doctor_json_does_not_count_fresh_incomplete_round_as_recent_artifact_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "artifact_fresh_round")
            complete_research_round(session_dir, "continue")
            with change_dir(root), redirect_stdout(StringIO()):
                self.assertEqual(main(["next", "--json"]), 0)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertEqual(store.read_json(session_dir / "state.json")["round"], 2)
            self.assertNotIn("no_recent_artifacts_after_multiple_rounds", result["warnings"])

    def test_doctor_json_does_not_warn_for_recent_artifact_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "artifact_present")
            complete_research_round(session_dir, "continue")
            with change_dir(root), redirect_stdout(StringIO()):
                self.assertEqual(main(["next", "--json"]), 0)
            round_two = session_dir / "rounds" / "002"
            (round_two / "review.md").write_text(complete_review("continue"), encoding="utf-8")
            (round_two / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
            (round_two / "evidence.md").write_text(COMPLETE_RESEARCH_EVIDENCE, encoding="utf-8")
            (round_two / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
            (root / "artifacts").mkdir()
            (root / "artifacts" / "recent.log").write_text("recent evidence\n", encoding="utf-8")
            (session_dir / "artifact-manifest.json").write_text(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": "EV2",
                                "kind": "log",
                                "round": 2,
                                "description": "recent evidence",
                                "path": "artifacts/recent.log",
                            }
                        ]
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())
            with change_dir(root), redirect_stdout(StringIO()):
                self.assertEqual(main(["next", "--json"]), 0)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertNotIn("no_recent_artifacts_after_multiple_rounds", result["warnings"])

    def test_repeated_next_smallest_step_is_agent_review_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "step_warn")
            complete_research_round(session_dir, "continue")
            with change_dir(root), redirect_stdout(StringIO()):
                self.assertEqual(main(["next", "--json"]), 0)
            round_two = session_dir / "rounds" / "002"
            (round_two / "review.md").write_text(complete_review("continue"), encoding="utf-8")
            (round_two / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
            (round_two / "evidence.md").write_text(COMPLETE_RESEARCH_EVIDENCE, encoding="utf-8")
            (round_two / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertNotIn("unchanged_next_smallest_step_across_rounds", result["warnings"])

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["review", "--pack", "--json"]), 0)
            review_result = json.loads(stdout.getvalue())
            signal_codes = {signal["code"] for signal in review_result["details"]["review_pack"]["agent_review_signals"]}
            self.assertIn("unchanged_next_smallest_step_across_rounds", signal_codes)

    def test_next_json_blocks_for_missing_readiness_records_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["action"], "next")
            self.assertEqual(result["details"]["gate"]["gate_status"], "blocked")
            codes = {blocker["code"] for blocker in result["blockers"]}
            self.assertIn("missing_review", codes)
            self.assertIn("missing_decision", codes)
            gate_codes = {finding["code"] for finding in result["details"]["gate"]["findings"]}
            self.assertIn("missing_review", gate_codes)
            self.assertFalse((session_dir / "rounds" / "002").exists())
            self.assertEqual(store.read_json(session_dir / "state.json")["round"], 1)

    def test_next_json_blocks_close_decision_outside_full_review_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "next_close_checkpoint", profile="checkpoint")
            round_dir = session_dir / "rounds" / "001"
            (round_dir / "evidence.md").write_text(COMPLETE_RESEARCH_EVIDENCE, encoding="utf-8")
            (round_dir / "decision.md").write_text(complete_decision("close-positive", "claim"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertIn("close_requires_full_review_profile", {blocker["code"] for blocker in result["blockers"]})
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_next_json_blocks_for_missing_research_evidence_and_interpretation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            round_dir = session_dir / "rounds" / "001"
            (round_dir / "review.md").write_text(complete_review("continue"), encoding="utf-8")
            (round_dir / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            codes = {blocker["code"] for blocker in result["blockers"]}
            self.assertIn("missing_research_evidence", codes)
            self.assertIn("missing_interpretation", codes)
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_next_json_blocks_for_missing_artifact_citation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")
            decision_path = session_dir / "rounds" / "001" / "decision.md"
            decision_path.write_text(
                decision_path.read_text(encoding="utf-8").replace("Evidence: fixture evidence", "Evidence: [artifact:ART-1]"),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertIn("missing_artifact_citation", {blocker["code"] for blocker in result["blockers"]})
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_next_json_ignores_plain_artifact_like_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")
            decision_path = session_dir / "rounds" / "001" / "decision.md"
            decision_path.write_text(
                decision_path.read_text(encoding="utf-8").replace("Evidence: fixture evidence", "Evidence: ART-1 and RUN-12"),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "ok")
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())

    def test_next_json_blocks_for_missing_evidence_artifacts_table_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")
            evidence_path = session_dir / "rounds" / "001" / "evidence.md"
            evidence_path.write_text(
                evidence_path.read_text(encoding="utf-8")
                + "\n## Evidence Artifacts\n\n"
                "| ID | Kind | Path or URL | Supports | Notes |\n"
                "|---|---|---|---|---|\n"
                "| EV-MISSING | log | artifacts/missing.log | claim | fixture |\n",
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertIn("missing_artifact_citation", {blocker["code"] for blocker in result["blockers"]})
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_next_json_accepts_evidence_artifacts_table_id_in_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")
            evidence_path = session_dir / "rounds" / "001" / "evidence.md"
            evidence_path.write_text(
                evidence_path.read_text(encoding="utf-8")
                + "\n## Evidence Artifacts\n\n"
                "| ID | Kind | Path or URL | Supports | Notes |\n"
                "|---|---|---|---|---|\n"
                "| EV-OK | log | artifacts/ok.log | claim | fixture |\n",
                encoding="utf-8",
            )
            (root / "artifacts").mkdir()
            (root / "artifacts" / "ok.log").write_text("fixture evidence artifact\n", encoding="utf-8")
            (session_dir / "artifact-manifest.json").write_text(
                json.dumps(
                    {
                        "artifacts": [
                            {
                                "id": "EV-OK",
                                "kind": "log",
                                "path": "artifacts/ok.log",
                                "round": 1,
                                "description": "Fixture evidence artifact",
                            }
                        ]
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "ok")
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())

    def test_next_json_blocks_for_existing_next_round_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")
            next_round = session_dir / "rounds" / "002"
            next_round.mkdir()
            sentinel = next_round / "prompt.md"
            sentinel.write_text(
                "<!-- rdl:managed policy=managed_prefix -->\n# Existing Prompt\n<!-- /rdl:managed -->\n",
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())
            before = {
                "progress": (session_dir / "progress.md").read_text(encoding="utf-8"),
                "ledger": (session_dir / "decision-ledger.md").read_text(encoding="utf-8"),
                "integrity": (session_dir / "integrity.json").read_text(encoding="utf-8"),
            }

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["next", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blockers"][0]["code"], "next_round_exists")
            self.assertIn("# Existing Prompt", sentinel.read_text(encoding="utf-8"))
            self.assertEqual(store.read_json(session_dir / "state.json")["round"], 1)
            self.assertEqual((session_dir / "progress.md").read_text(encoding="utf-8"), before["progress"])
            self.assertEqual((session_dir / "decision-ledger.md").read_text(encoding="utf-8"), before["ledger"])
            self.assertEqual((session_dir / "integrity.json").read_text(encoding="utf-8"), before["integrity"])

    def test_next_json_errors_when_integrity_refresh_fails_after_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["memory", "--write", "--json"]), 0)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                with patch("rdl.commands.integrity.refresh", side_effect=ValueError("refresh failed")):
                    self.assertEqual(main(["next", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "next")
            self.assertEqual(result["blockers"][0]["code"], "integrity_refresh_failed")
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())

    def test_next_without_json_no_longer_raises_unsupported_parser_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
                self.assertEqual(main(["next"]), 0)

            self.assertIn("ok: next", stdout.getvalue())
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())


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

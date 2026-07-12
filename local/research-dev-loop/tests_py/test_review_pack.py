import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from rdl import review_pack
from rdl.session import SessionStore

from rdl_test_support import (
    COMPLETE_INTERPRETATION,
    REPEATED_NEGATIVE_EVIDENCE,
    complete_decision,
    complete_research_round,
    complete_review,
    create_session,
    set_current_round,
    write_json,
)


class ReviewPackTests(unittest.TestCase):
    def test_builds_clean_rdl_context_pack_without_conversation_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack")
            complete_research_round(session_dir)
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(
                details={
                    "findings": [
                        {"category": "memory", "code": "session_memory_needs_attention"},
                        {"category": "semantic", "code": "semantic_review_recorded"},
                    ]
                }
            )

            pack = review_pack.build(session, "doctor", deterministic_report)

            record_paths = {record["path"] for record in pack.records}
            self.assertIn("progress.md", record_paths)
            self.assertIn("rounds/001/review.md", record_paths)
            self.assertEqual([finding["code"] for finding in pack.deterministic_findings], ["session_memory_needs_attention"])
            rendered = pack.as_dict()
            self.assertNotIn("conversation", rendered)
            self.assertNotIn("conversation_history", rendered)
            self.assertIn("text", rendered["records"][0])
            self.assertIn("reviewer_task", rendered)
            self.assertIn("finding_schema", rendered)
            self.assertIn("agent_review_signals", rendered)
            self.assertRegex(pack.subject_digest, r"^sha256:[0-9a-f]{64}$")
            self.assertEqual(rendered["subject_digest"], pack.subject_digest)
            self.assertEqual(pack.summary()["subject_digest"], pack.subject_digest)

    def test_reviewer_task_requires_exact_subject_echo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_echo")
            complete_research_round(session_dir)
            session = SessionStore(root).active_session()

            pack = review_pack.build(session, "next", SimpleNamespace(details={"findings": []}))

            output = pack.reviewer_task["output"]
            self.assertEqual(output["subject_action"], "echo review_pack.action exactly")
            self.assertEqual(output["subject_digest"], "echo review_pack.subject_digest exactly")

    def test_subject_digest_ignores_current_review_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_review_change")
            complete_research_round(session_dir)
            session = SessionStore(root).active_session()
            report = SimpleNamespace(details={"findings": []})
            before = review_pack.build(session, "next", report).subject_digest
            review_file = session.round_dir() / "review.md"
            review_file.write_text(
                review_file.read_text(encoding="utf-8").replace("none\n", "accepted review-only note\n", 1),
                encoding="utf-8",
            )

            after = review_pack.build(SessionStore(root).active_session(), "next", report).subject_digest

            self.assertEqual(after, before)

    def test_current_review_artifact_citation_does_not_expand_subject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_review_citation")
            complete_research_round(session_dir)
            _complete_prior_round(session_dir, 2)
            _complete_prior_round(session_dir, 3)
            round_four = set_current_round(session_dir, 4)
            (round_four / "review.md").write_text(complete_review("continue"), encoding="utf-8")
            write_json(
                session_dir / "artifact-manifest.json",
                {
                    "artifacts": [
                        {
                            "id": "OLD-ONLY-IN-REVIEW",
                            "kind": "log",
                            "round": 1,
                            "description": "Review-only citation must not expand the subject.",
                            "path": "artifacts/old.log",
                        }
                    ]
                },
            )
            report = SimpleNamespace(details={"findings": []})
            before_pack = review_pack.build(SessionStore(root).active_session(), "next", report)
            review_file = round_four / "review.md"
            review_file.write_text(
                review_file.read_text(encoding="utf-8") + "\nReview note [artifact:OLD-ONLY-IN-REVIEW].\n",
                encoding="utf-8",
            )
            after_pack = review_pack.build(SessionStore(root).active_session(), "next", report)

            self.assertEqual(after_pack.subject_digest, before_pack.subject_digest)
            self.assertNotIn("rounds/001/evidence.md", {record["path"] for record in after_pack.records})

    def test_subject_digest_changes_with_evidence_and_final_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_subject_change")
            complete_research_round(session_dir, "close-positive")
            final_report = session_dir / "final-report.md"
            final_report.write_text("# Final Report\n\nInitial close scope.\n", encoding="utf-8")
            report = SimpleNamespace(details={"findings": []})
            session = SessionStore(root).active_session()
            initial = review_pack.build(session, "close", report).subject_digest
            evidence_file = session.round_dir() / "evidence.md"
            evidence_file.write_text(evidence_file.read_text(encoding="utf-8") + "\nNew evidence.\n", encoding="utf-8")
            evidence_digest = review_pack.build(SessionStore(root).active_session(), "close", report).subject_digest
            final_report.write_text("# Final Report\n\nRevised close scope.\n", encoding="utf-8")
            report_digest = review_pack.build(SessionStore(root).active_session(), "close", report).subject_digest

            self.assertNotEqual(evidence_digest, initial)
            self.assertNotEqual(report_digest, evidence_digest)

    def test_subject_digest_changes_with_subject_records(self):
        cases = (
            ("mission.md", "\nMission clarification.\n"),
            ("rounds/001/interpretation.md", "\nInterpretation clarification.\n"),
            ("rounds/001/decision.md", "\nDecision clarification.\n"),
            ("progress.md", "\nHuman progress note.\n"),
            ("factors.md", "\nHuman factor note.\n"),
            ("decision-ledger.md", "\nHuman ledger note.\n"),
        )
        for relative, addition in cases:
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                session_dir = create_session(root, f"review_pack_change_{Path(relative).stem}")
                complete_research_round(session_dir)
                report = SimpleNamespace(details={"findings": []})
                before = review_pack.build(SessionStore(root).active_session(), "next", report).subject_digest
                path = session_dir / relative
                path.write_text(path.read_text(encoding="utf-8") + addition, encoding="utf-8")
                after = review_pack.build(SessionStore(root).active_session(), "next", report).subject_digest

                self.assertNotEqual(after, before)

    def test_subject_digest_is_stable_when_findings_and_signals_reorder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_input_order")
            complete_research_round(session_dir)
            session = SessionStore(root).active_session()
            findings = (
                {"severity": "warning", "category": "artifact", "code": "artifact_b", "location": "b"},
                {"severity": "blocking", "category": "evidence", "code": "evidence_a", "location": "a"},
            )
            signals = (
                {"code": "signal_b", "location": "b", "message": "second", "review_prompt": "review second"},
                {"code": "signal_a", "location": "a", "message": "first", "review_prompt": "review first"},
            )

            with patch("rdl.review_pack.memory.agent_review_signals", return_value=signals):
                first = review_pack.build(
                    session,
                    "next",
                    SimpleNamespace(details={"findings": list(findings)}),
                ).subject_digest
            with patch("rdl.review_pack.memory.agent_review_signals", return_value=tuple(reversed(signals))):
                reordered = review_pack.build(
                    session,
                    "next",
                    SimpleNamespace(details={"findings": list(reversed(findings))}),
                ).subject_digest

            self.assertEqual(reordered, first)

    def test_subject_digest_canonicalizes_manifest_object_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_manifest_digest")
            complete_research_round(session_dir)
            manifest_path = session_dir / "artifact-manifest.json"
            manifest_path.write_text('{"artifacts": [], "metadata": {"b": 2, "a": 1}}\n', encoding="utf-8")
            report = SimpleNamespace(details={"findings": []})
            before = review_pack.build(SessionStore(root).active_session(), "next", report).subject_digest
            manifest_path.write_text('{"metadata": {"a": 1, "b": 2}, "artifacts": []}\n', encoding="utf-8")
            reordered = review_pack.build(SessionStore(root).active_session(), "next", report).subject_digest
            manifest_path.write_text('{"metadata": {"a": 1, "b": 3}, "artifacts": []}\n', encoding="utf-8")
            changed = review_pack.build(SessionStore(root).active_session(), "next", report).subject_digest

            self.assertEqual(reordered, before)
            self.assertNotEqual(changed, reordered)

    def test_subject_digest_ignores_generated_summary_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_summary_digest")
            complete_research_round(session_dir)
            report = SimpleNamespace(details={"findings": []})
            session = SessionStore(root).active_session()
            before = review_pack.build(session, "next", report).subject_digest
            from rdl import summary

            summary_plan = summary.plan(session)
            self.assertFalse(summary.write(session, summary_plan))
            after = review_pack.build(SessionStore(root).active_session(), "next", report).subject_digest

            self.assertEqual(after, before)

    def test_malformed_generated_summary_marker_is_not_stripped(self):
        from rdl import summary

        text = "# Progress\n\n<!-- rdl:summary section=Completed start -->\nHuman text after malformed marker.\n"

        self.assertEqual(summary.without_generated_blocks("progress.md", text), text)

    def test_subject_digest_binds_normalized_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_action_digest")
            complete_research_round(session_dir)
            session = SessionStore(root).active_session()
            report = SimpleNamespace(details={"findings": []})

            advance = review_pack.build(session, "advance", report)
            next_pack = review_pack.build(session, "next", report)
            close = review_pack.build(session, "close", report)

            self.assertEqual(advance.subject_digest, next_pack.subject_digest)
            self.assertNotEqual(close.subject_digest, next_pack.subject_digest)

    def test_repeated_next_step_is_agent_review_signal_not_deterministic_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_signal", profile="checkpoint")
            complete_research_round(session_dir)
            round_two = set_current_round(session_dir, 2)
            (round_two / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(details={"findings": []})

            pack = review_pack.build(session, "review", deterministic_report)

            self.assertIn("unchanged_next_smallest_step_across_rounds", {signal["code"] for signal in pack.agent_review_signals})
            self.assertEqual(pack.deterministic_findings, ())

    def test_semantic_consumption_findings_are_not_deterministic_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_semantic_filter")
            complete_research_round(session_dir)
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(
                details={
                    "findings": [
                        {"category": "protocol", "code": "missing_decision"},
                        {"category": "semantic", "code": "missing_semantic_review"},
                        {"category": "semantic", "code": "semantic_review_blocked"},
                        {"category": "semantic", "code": "semantic_review_decision_mismatch"},
                    ]
                }
            )

            pack = review_pack.build(session, "review", deterministic_report)

            self.assertEqual([finding["code"] for finding in pack.deterministic_findings], ["missing_decision"])

    def test_filters_expected_missing_review_findings_but_keeps_other_deterministic_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_expected_absence")
            complete_research_round(session_dir)
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(
                details={
                    "findings": [
                        {"category": "protocol", "code": "missing_review"},
                        {"category": "semantic", "code": "missing_semantic_review"},
                        {"category": "evidence", "code": "missing_evidence"},
                        {"category": "artifact", "code": "artifact_drift"},
                    ]
                }
            )

            pack = review_pack.build(session, "review", deterministic_report)

            self.assertEqual(
                [finding["code"] for finding in pack.deterministic_findings],
                ["missing_evidence", "artifact_drift"],
            )

    def test_advance_action_normalizes_to_next_everywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_advance")
            complete_research_round(session_dir)
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(details={"findings": []})

            pack = review_pack.build(session, "advance", deterministic_report)

            self.assertEqual(pack.action, "next")
            self.assertEqual(pack.as_dict()["reviewer_task"]["action"], "next")
            self.assertEqual(pack.summary()["action"], "next")
            self.assertIn("next smallest step", "\n".join(pack.reviewer_task["questions"]))

    def test_reviewer_task_is_action_profile_mode_aware_without_large_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_task", mode="build")
            set_current_round(session_dir, 1)
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(details={"findings": []})

            pack = review_pack.build(session, "close", deterministic_report)

            task = pack.as_dict()["reviewer_task"]
            self.assertEqual(task["action"], "close")
            self.assertEqual(task["mode"], "build")
            self.assertEqual(task["profile"], "full-review")
            self.assertIn("finding_line_format", task["output"])
            joined_questions = "\n".join(task["questions"])
            self.assertIn("close outcome", joined_questions)
            self.assertIn("work artifacts", joined_questions)
            self.assertLessEqual(len(task["questions"]), 7)

    def test_includes_bounded_prior_completed_round_key_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_history")
            complete_research_round(session_dir)
            _complete_prior_round(session_dir, 2)
            _complete_prior_round(session_dir, 3)
            set_current_round(session_dir, 4)
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(details={"findings": []})

            pack = review_pack.build(session, "review", deterministic_report)

            record_paths = [record["path"] for record in pack.records]
            self.assertIn("rounds/004/prompt.md", record_paths)
            for round_number in (2, 3):
                for file_name in ("evidence.md", "interpretation.md", "review.md", "decision.md", "events.md"):
                    self.assertIn(f"rounds/{round_number:03d}/{file_name}", record_paths)
                self.assertNotIn(f"rounds/{round_number:03d}/prompt.md", record_paths)
                self.assertNotIn(f"rounds/{round_number:03d}/intent.md", record_paths)
                self.assertNotIn(f"rounds/{round_number:03d}/work.md", record_paths)
            self.assertNotIn("rounds/001/evidence.md", record_paths)

    def test_includes_cited_artifact_round_records_outside_prior_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_cited_artifact")
            complete_research_round(session_dir)
            (session_dir / "rounds" / "001" / "events.md").write_text(
                "# Events\n\n## Operational Events\n\nOlder artifact-producing round event.\n",
                encoding="utf-8",
            )
            _complete_prior_round(session_dir, 2)
            _complete_prior_round(session_dir, 3)
            _complete_prior_round(session_dir, 4)
            round_five = set_current_round(session_dir, 5)
            (round_five / "decision.md").write_text(
                complete_decision("close-positive", "claim").replace("Evidence: fixture evidence", "Evidence: [artifact:OLD-RUN]"),
                encoding="utf-8",
            )
            write_json(
                session_dir / "artifact-manifest.json",
                {
                    "artifacts": [
                        {
                            "id": "OLD-RUN",
                            "kind": "log",
                            "round": 1,
                            "description": "Older cited evidence outside the recent prior-round window.",
                            "path": "artifacts/old-run.log",
                        }
                    ]
                },
            )
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(details={"findings": []})

            pack = review_pack.build(session, "review", deterministic_report)

            record_paths = [record["path"] for record in pack.records]
            for file_name in ("evidence.md", "interpretation.md", "review.md", "decision.md", "events.md"):
                self.assertIn(f"rounds/001/{file_name}", record_paths)
            self.assertNotIn("rounds/001/prompt.md", record_paths)
            self.assertNotIn("rounds/001/intent.md", record_paths)
            self.assertNotIn("rounds/001/work.md", record_paths)

    def test_ignores_malformed_cited_artifact_round_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_bad_artifact_round")
            complete_research_round(session_dir)
            _complete_prior_round(session_dir, 2)
            _complete_prior_round(session_dir, 3)
            set_current_round(session_dir, 4)
            round_four = session_dir / "rounds" / "004"
            (round_four / "evidence.md").write_text(
                "# Evidence\n\n## Evidence Artifacts\n\n| ID | Kind |\n|---|---|\n| BAD-RUN | log |\n",
                encoding="utf-8",
            )
            write_json(
                session_dir / "artifact-manifest.json",
                {
                    "artifacts": [
                        {
                            "id": "BAD-RUN",
                            "kind": "log",
                            "round": "1",
                            "description": "Malformed round metadata should not select old records.",
                            "path": "artifacts/bad-run.log",
                        },
                        {
                            "id": "FUTURE-RUN",
                            "kind": "log",
                            "round": 6,
                            "description": "Future rounds should not select records.",
                            "path": "artifacts/future-run.log",
                        },
                    ]
                },
            )
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(details={"findings": []})

            pack = review_pack.build(session, "review", deterministic_report)

            record_paths = {record["path"] for record in pack.records}
            self.assertNotIn("rounds/001/evidence.md", record_paths)
            self.assertIn("rounds/002/evidence.md", record_paths)
            self.assertIn("rounds/003/evidence.md", record_paths)

    def test_repeated_negative_evidence_after_continue_is_agent_review_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_repeated_negative")
            complete_research_round(session_dir, "continue")
            round_two = set_current_round(session_dir, 2)
            (round_two / "evidence.md").write_text(REPEATED_NEGATIVE_EVIDENCE, encoding="utf-8")
            (round_two / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
            (round_two / "review.md").write_text(complete_review("close-negative"), encoding="utf-8")
            (round_two / "decision.md").write_text(complete_decision("close-negative", "claim"), encoding="utf-8")
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(details={"findings": []})

            pack = review_pack.build(session, "review", deterministic_report)

            self.assertIn(
                "repeated_negative_evidence_after_continue",
                {signal["code"] for signal in pack.agent_review_signals},
            )
            self.assertEqual(pack.deterministic_findings, ())


def _complete_prior_round(session_dir: Path, round_number: int) -> None:
    round_dir = set_current_round(session_dir, round_number)
    (round_dir / "evidence.md").write_text(f"# Evidence\n\nResearch evidence from round {round_number}.\n", encoding="utf-8")
    (round_dir / "interpretation.md").write_text(f"# Interpretation\n\nInterpretation from round {round_number}.\n", encoding="utf-8")
    (round_dir / "review.md").write_text(complete_review("continue"), encoding="utf-8")
    (round_dir / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
    (round_dir / "events.md").write_text(f"# Events\n\n## Operational Events\n\nRound {round_number} event.\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

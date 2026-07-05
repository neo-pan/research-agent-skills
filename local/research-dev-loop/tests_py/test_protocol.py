import unittest

from rdl.model import RoundProfile, SessionMode
from rdl.protocol import descriptor


class ProtocolDescriptorTests(unittest.TestCase):
    def test_session_files(self):
        self.assertEqual(
            descriptor.required_session_files(),
            (
                "state.json",
                "mission.md",
                "factors.md",
                "artifact-manifest.json",
                "decision-ledger.md",
                "progress.md",
            ),
        )
        self.assertEqual(descriptor.optional_session_files(), ("final-report.md",))
        self.assertEqual(
            descriptor.initialized_session_templates(),
            (
                "factors.md",
                "artifact-manifest.json",
                "decision-ledger.md",
                "progress.md",
            ),
        )

    def test_round_files(self):
        self.assertEqual(
            descriptor.round_file_names(),
            (
                "prompt.md",
                "intent.md",
                "work.md",
                "events.md",
                "evidence.md",
                "interpretation.md",
                "review.md",
                "decision.md",
                "gate-report.json",
                "gate.md",
            ),
        )
        self.assertEqual(
            descriptor.completed_round_files(SessionMode.RESEARCH),
            ("prompt.md", "evidence.md", "interpretation.md", "review.md", "decision.md"),
        )
        self.assertEqual(
            descriptor.completed_round_files("build"),
            ("prompt.md", "intent.md", "work.md", "evidence.md", "review.md", "decision.md"),
        )
        self.assertEqual(descriptor.completed_round_files("research", "checkpoint"), ("prompt.md", "evidence.md", "decision.md"))
        self.assertEqual(descriptor.completed_round_files("build", "build-update"), ("prompt.md", "intent.md", "work.md", "evidence.md", "decision.md"))
        self.assertEqual(descriptor.completed_round_files("research", "build-update"), ())

    def test_required_fields_and_sections(self):
        self.assertIn("Recommended Decision", descriptor.required_fields("review"))
        self.assertIn("Next smallest step", descriptor.required_fields("decision"))
        self.assertEqual(
            descriptor.required_fields("review"),
            (
                "Reviewer",
                "Review Mode",
                "Review Scope",
                "Artifacts Reviewed",
                "Verdict",
                "Decision Reviewed",
                "Evidence Reviewed",
                "Blocking Evidence Gaps",
                "Implementation Findings",
                "Evaluation Integrity Findings",
                "Overclaim Risks",
                "Fresh Evidence",
                "Staleness Signal",
                "Direction Reuse Risk",
                "Readiness Level",
                "Recommended Decision",
            ),
        )
        self.assertEqual(
            descriptor.required_fields("decision"),
            (
                "Decision",
                "Closes",
                "Evidence",
                "Uncertainty",
                "What this rules out",
                "What remains unknown",
                "Direction changed",
                "Prior directions checked",
                "Stall response",
                "Recommended next loop",
                "Next smallest step",
            ),
        )
        self.assertEqual(
            descriptor.required_sections("progress"),
            ("Active", "Completed", "Blocked", "Deferred", "Open Questions", "Directions Tried", "Staleness Watch"),
        )
        self.assertEqual(
            descriptor.required_sections("final-report"),
            (
                "Outcome",
                "Claim or Capability Closed",
                "Evidence Cited",
                "Missing Evidence and Confounders",
                "Negative, Null, or Inconclusive Results",
                "Open Questions",
                "Deferred Items",
                "Directions Tried And Stall Responses",
                "Reusable Lessons",
                "Close Checklist",
            ),
        )

    def test_allowed_values(self):
        self.assertTrue(descriptor.value_allowed("review-mode", "manual"))
        self.assertTrue(descriptor.value_allowed("round-profile", "checkpoint"))
        self.assertTrue(descriptor.value_allowed("review-verdict", "PASS"))
        self.assertTrue(descriptor.value_allowed("decision-type", "close-positive"))
        self.assertTrue(descriptor.value_allowed("recommended-next-loop", "none"))
        self.assertTrue(descriptor.value_allowed("close-outcome", "positive"))

        self.assertFalse(descriptor.value_allowed("review-mode", "unsupported"))
        self.assertFalse(descriptor.value_allowed("round-profile", "audit"))
        self.assertFalse(descriptor.value_allowed("review-verdict", "MAYBE"))
        self.assertFalse(descriptor.value_allowed("decision-type", "close-unknown"))
        self.assertFalse(descriptor.value_allowed("recommended-next-loop", "deploy"))
        self.assertFalse(descriptor.value_allowed("close-outcome", "partial"))

    def test_expected_closes(self):
        self.assertEqual(descriptor.expected_closes("research"), "claim")
        self.assertEqual(descriptor.expected_closes(SessionMode.BUILD), "capability")
        self.assertEqual(descriptor.expected_closes("unknown"), "")

    def test_prompt_expected_exit_decision(self):
        self.assertEqual(descriptor.prompt_expected_exit_decision("research"), "claim decision with evidence and uncertainty")
        self.assertEqual(descriptor.prompt_expected_exit_decision(SessionMode.BUILD), "capability decision with verification evidence")
        self.assertEqual(descriptor.prompt_expected_exit_decision("research", "checkpoint"), "checkpoint decision with evidence")
        self.assertEqual(descriptor.prompt_expected_exit_decision("build", "build-update"), "build update decision with verification evidence")
        self.assertEqual(descriptor.prompt_expected_exit_decision("research", "build-update"), "")
        self.assertEqual(descriptor.prompt_expected_exit_decision("unknown"), "")

    def test_known_paths(self):
        self.assertTrue(descriptor.path_known("state.json"))
        self.assertTrue(descriptor.path_known("final-report.md"))
        self.assertTrue(descriptor.path_known("rounds/001/prompt.md"))
        self.assertTrue(descriptor.path_known("rounds/001/events.md"))
        self.assertTrue(descriptor.path_known("rounds/999/evidence.md"))

        for path in (
            "",
            "/state.json",
            ".",
            "..",
            "./state.json",
            "../state.json",
            "rounds/1/prompt.md",
            "rounds/001/nested/prompt.md",
            "rounds/001/notes.md",
            "rounds/001/../prompt.md",
        ):
            with self.subTest(path=path):
                self.assertFalse(descriptor.path_known(path))

    def test_policy_for_path(self):
        self.assertEqual(descriptor.policy_for_path("state.json"), "cli_owned")
        self.assertEqual(descriptor.policy_for_path("decision-ledger.md"), "append_only")
        self.assertEqual(descriptor.policy_for_path("rounds/001/prompt.md"), "managed_prefix")
        self.assertEqual(descriptor.policy_for_path("rounds/001/evidence.md"), "human_owned")
        self.assertEqual(descriptor.policy_for_path("rounds/001/nested/prompt.md"), "human_owned")

    def test_readiness_plans_are_described_but_not_executed(self):
        self.assertEqual(
            descriptor.readiness_plan("advance"),
            (
                "review",
                "decision",
                "review-decision-alignment",
                "staleness-response",
                "mode-minimums",
                "round-evidence-discipline",
                "artifact-citations",
                "close-if-decision",
            ),
        )
        self.assertIn("final-report", descriptor.readiness_plan("close"))
        self.assertIn("full-review-close-profile", descriptor.readiness_plan("close"))

    def test_document_specs_collect_fields_sections_and_values(self):
        review = descriptor.document_spec("review")
        self.assertEqual(review.required_fields, descriptor.required_fields("review"))
        self.assertEqual(review.required_sections, ())
        self.assertEqual(review.values_for_field("Review Mode"), descriptor.allowed_values("review-mode"))
        self.assertEqual(review.values_for_field("Verdict"), descriptor.allowed_values("review-verdict"))

        decision = descriptor.document_spec("decision")
        self.assertEqual(decision.required_fields, descriptor.required_fields("decision"))
        self.assertEqual(decision.values_for_field("Decision"), descriptor.allowed_values("decision-type"))
        self.assertEqual(decision.values_for_field("Recommended next loop"), descriptor.allowed_values("recommended-next-loop"))

        final_report = descriptor.document_spec("final-report")
        self.assertEqual(final_report.required_sections, descriptor.required_sections("final-report"))
        self.assertEqual(final_report.required_fields, ())

        self.assertIsNone(descriptor.document_spec("unknown"))

    def test_mode_specs_collect_mode_protocol_facts(self):
        research = descriptor.mode_spec(SessionMode.RESEARCH)
        self.assertIsNotNone(research)
        self.assertEqual(research.completed_round_files, descriptor.completed_round_files("research"))
        self.assertEqual(research.expected_closes, "claim")
        self.assertEqual(research.prompt_expected_exit_decision, "claim decision with evidence and uncertainty")

        build = descriptor.mode_spec("build")
        self.assertIsNotNone(build)
        self.assertEqual(build.completed_round_files, descriptor.completed_round_files(SessionMode.BUILD))
        self.assertEqual(build.expected_closes, "capability")
        self.assertEqual(build.prompt_expected_exit_decision, "capability decision with verification evidence")

        self.assertIsNone(descriptor.mode_spec("unknown"))

    def test_profile_specs_collect_round_profile_protocol_facts(self):
        checkpoint = descriptor.profile_spec(RoundProfile.CHECKPOINT)
        self.assertIsNotNone(checkpoint)
        self.assertTrue(descriptor.profile_allowed_for_mode("research", "checkpoint"))
        self.assertTrue(descriptor.profile_allowed_for_mode(SessionMode.BUILD, RoundProfile.BUILD_UPDATE))
        self.assertFalse(descriptor.profile_allowed_for_mode("research", "build-update"))
        self.assertIsNone(descriptor.profile_spec("audit"))

    def test_close_outcome_for_decision_is_protocol_owned(self):
        self.assertEqual(descriptor.close_outcome_for_decision("close-positive"), "positive")
        self.assertEqual(descriptor.close_outcome_for_decision("close-negative"), "negative")
        self.assertEqual(descriptor.close_outcome_for_decision("close-inconclusive"), "inconclusive")
        self.assertEqual(descriptor.close_outcome_for_decision("continue"), "")

    def test_protocol_file_policy_for_known_and_unknown_paths(self):
        self.assertEqual(descriptor.path_policy("state.json"), "cli_owned")
        self.assertEqual(descriptor.path_policy("decision-ledger.md"), "append_only")
        self.assertEqual(descriptor.path_policy("rounds/001/prompt.md"), "managed_prefix")
        self.assertEqual(descriptor.path_policy("rounds/001/evidence.md"), "human_owned")
        self.assertIsNone(descriptor.path_policy("../state.json"))
        self.assertIsNone(descriptor.path_policy("rounds/001/notes.md"))


if __name__ == "__main__":
    unittest.main()

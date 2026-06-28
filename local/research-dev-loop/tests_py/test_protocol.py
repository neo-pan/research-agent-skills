import unittest

from rdl.model import SessionMode
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

    def test_round_files(self):
        self.assertEqual(
            descriptor.round_file_names(),
            (
                "prompt.md",
                "intent.md",
                "work.md",
                "evidence.md",
                "interpretation.md",
                "review.md",
                "decision.md",
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

    def test_required_fields_and_sections(self):
        self.assertIn("Recommended Decision", descriptor.required_fields("review"))
        self.assertIn("Next smallest step", descriptor.required_fields("decision"))
        self.assertEqual(
            descriptor.required_sections("progress"),
            ("Active", "Completed", "Blocked", "Deferred", "Open Questions"),
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
                "Reusable Lessons",
                "Close Checklist",
            ),
        )

    def test_allowed_values(self):
        self.assertTrue(descriptor.value_allowed("review-mode", "manual"))
        self.assertTrue(descriptor.value_allowed("review-verdict", "PASS"))
        self.assertTrue(descriptor.value_allowed("decision-type", "close-positive"))
        self.assertTrue(descriptor.value_allowed("recommended-next-loop", "none"))
        self.assertTrue(descriptor.value_allowed("close-outcome", "positive"))

        self.assertFalse(descriptor.value_allowed("review-mode", "unsupported"))
        self.assertFalse(descriptor.value_allowed("review-verdict", "MAYBE"))
        self.assertFalse(descriptor.value_allowed("decision-type", "close-unknown"))
        self.assertFalse(descriptor.value_allowed("recommended-next-loop", "deploy"))
        self.assertFalse(descriptor.value_allowed("close-outcome", "partial"))

    def test_expected_closes(self):
        self.assertEqual(descriptor.expected_closes("research"), "claim")
        self.assertEqual(descriptor.expected_closes(SessionMode.BUILD), "capability")
        self.assertEqual(descriptor.expected_closes("unknown"), "")

    def test_known_paths(self):
        self.assertTrue(descriptor.path_known("state.json"))
        self.assertTrue(descriptor.path_known("final-report.md"))
        self.assertTrue(descriptor.path_known("rounds/001/prompt.md"))
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
                "mode-minimums",
                "round-evidence-discipline",
                "artifact-citations",
            ),
        )
        self.assertIn("final-report", descriptor.readiness_plan("close"))


if __name__ == "__main__":
    unittest.main()

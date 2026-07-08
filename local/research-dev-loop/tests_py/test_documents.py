import tempfile
import unittest
from pathlib import Path

from rdl import documents


class DocumentTests(unittest.TestCase):
    def test_field_extracts_trimmed_value(self):
        with markdown("# Review\n\nReviewer:  fixture \n") as path:
            self.assertEqual(documents.field(path, "Reviewer"), "fixture")

    def test_field_text_extracts_continuation_lines(self):
        with markdown(
            "# Decision\n\n"
            "What remains unknown: whether a stronger external index,\n"
            "graph-aware retriever, or curated artifact would help.\n"
            "\n"
            "Uncertainty: bounded\n"
        ) as path:
            self.assertEqual(
                documents.field_text(path, "What remains unknown"),
                "whether a stronger external index,\ngraph-aware retriever, or curated artifact would help.",
            )
            self.assertEqual(documents.field(path, "What remains unknown"), "whether a stronger external index,")

    def test_section_extracts_level_two_content(self):
        with markdown("# Report\n\n## Outcome\n\npositive\n\n## Next\n\nlater\n") as path:
            section = documents.section(path, "Outcome")
            self.assertEqual(section.content.strip(), "positive")
            self.assertIsNotNone(section.start_line)

    def test_content_detection_ignores_template_only_markdown(self):
        with markdown(
            "# Evidence\n\n"
            "## Evidence Artifacts\n\n"
            "| ID | Kind |\n"
            "|---|---|\n\n"
            "## Strength of Support\n\n"
            "Strong | Moderate | Weak | Contradicted | Inconclusive\n"
        ) as path:
            self.assertFalse(documents.has_content(path))

    def test_content_detection_accepts_meaningful_table_row(self):
        with markdown("| ID | Kind |\n|---|---|\n| E1 | log |\n") as path:
            self.assertTrue(documents.has_content(path))

    def test_section_content_detection(self):
        with markdown("# Evidence\n\n## Missing Evidence\n\nNone blocking.\n") as path:
            self.assertTrue(documents.section_has_content(path, "Missing Evidence"))
            self.assertFalse(documents.section_has_content(path, "Evaluation Integrity"))

    def test_unchecked_checklist_does_not_satisfy_section_content(self):
        with markdown("# Final Report\n\n## Close Checklist\n\n- [ ] Final decision is positive.\n") as path:
            self.assertFalse(documents.section_has_content(path, "Close Checklist"))

    def test_checked_checklist_satisfies_section_content(self):
        with markdown("# Final Report\n\n## Close Checklist\n\n- [x] Final decision is positive.\n") as path:
            self.assertTrue(documents.section_has_content(path, "Close Checklist"))

    def test_missing_file_has_no_content(self):
        self.assertFalse(documents.has_content(Path("/tmp/rdl-definitely-missing-file.md")))

    def test_extract_artifact_ids(self):
        self.assertEqual(documents.extract_artifact_ids("See [artifact:E1], [artifact:RUN-12], and E2."), {"E1", "RUN-12"})
        self.assertEqual(documents.extract_artifact_ids("See `E1`, RUN-12, and abc."), set())

    def test_complete_review_validates(self):
        with markdown(COMPLETE_REVIEW) as path:
            self.assertEqual(documents.validate("review", path), [])

    def test_review_validation_blocks_missing_file_and_invalid_values(self):
        blockers = documents.validate("review", Path("/tmp/rdl-missing-review.md"))
        self.assertEqual([blocker.code for blocker in blockers], ["missing_review"])

        content = (
            COMPLETE_REVIEW.replace("Review Mode: manual", "Review Mode: unsupported")
            .replace("Verdict: PASS", "Verdict: MAYBE")
            .replace("Fresh Evidence: yes", "Fresh Evidence: stale")
            .replace("Staleness Signal: none", "Staleness Signal: stuck")
            .replace("Direction Reuse Risk: low", "Direction Reuse Risk: extreme")
        )
        with markdown(content) as path:
            codes = {blocker.code for blocker in documents.validate("review", path)}
            self.assertIn("invalid_review_mode", codes)
            self.assertIn("invalid_review_verdict", codes)
            self.assertIn("invalid_fresh_evidence", codes)
            self.assertIn("invalid_staleness_signal", codes)
            self.assertIn("invalid_direction_reuse_risk", codes)

    def test_review_validation_blocks_placeholder_fields(self):
        with markdown(COMPLETE_REVIEW.replace("Recommended Decision: continue", "Recommended Decision:")) as path:
            codes = [blocker.code for blocker in documents.validate("review", path)]
            self.assertIn("missing_review_field", codes)

    def test_review_validation_blocks_malformed_structured_findings(self):
        malformed = COMPLETE_REVIEW.replace("- none", "- urgent | vibes | nowhere | vague")
        with markdown(malformed) as path:
            codes = {blocker.code for blocker in documents.validate("review", path)}
            self.assertIn("invalid_review_finding", codes)

    def test_complete_decision_validates_with_expected_closes(self):
        with markdown(COMPLETE_DECISION) as path:
            self.assertEqual(documents.validate("decision", path, {"expected_closes": "claim"}), [])

    def test_decision_validation_blocks_bad_values(self):
        content = (
            COMPLETE_DECISION.replace("Decision: continue", "Decision: close-unknown")
            .replace("Closes: claim", "Closes: capability")
            .replace("Direction changed: no", "Direction changed: maybe")
            .replace("Recommended next loop: none", "Recommended next loop: deploy")
        )
        with markdown(content) as path:
            codes = {blocker.code for blocker in documents.validate("decision", path, {"expected_closes": "claim"})}
            self.assertIn("invalid_decision_type", codes)
            self.assertIn("invalid_closes", codes)
            self.assertIn("invalid_direction_changed", codes)
            self.assertIn("invalid_recommended_next_loop", codes)

    def test_decision_validation_blocks_missing_file_and_placeholders(self):
        blockers = documents.validate("decision", Path("/tmp/rdl-missing-decision.md"))
        self.assertEqual([blocker.code for blocker in blockers], ["missing_decision"])

        with markdown(COMPLETE_DECISION.replace("Evidence: E1 fixture evidence", "Evidence:")) as path:
            codes = [blocker.code for blocker in documents.validate("decision", path)]
            self.assertIn("missing_decision_field", codes)

    def test_complete_final_report_validates(self):
        with markdown(COMPLETE_FINAL_REPORT) as path:
            self.assertEqual(documents.validate("final-report", path, {"outcome": "positive"}), [])

    def test_final_report_validation_blocks_missing_sections_and_checklist(self):
        incomplete = COMPLETE_FINAL_REPORT.replace("positive", "", 1).replace("- [x] Final decision", "- [ ] Final decision")
        with markdown(incomplete) as path:
            codes = {blocker.code for blocker in documents.validate("final-report", path, {"outcome": "positive"})}
            self.assertIn("missing_final_report_section", codes)
            self.assertIn("incomplete_close_checklist", codes)
            self.assertIn("close_outcome_mismatch", codes)

    def test_final_report_validation_treats_unchecked_close_checklist_as_missing_section_content(self):
        incomplete = COMPLETE_FINAL_REPORT.replace("- [x] Final decision", "- [ ] Final decision")
        with markdown(incomplete) as path:
            blockers = documents.validate("final-report", path, {"outcome": "positive"})
            self.assertIn(
                ("missing_final_report_section", f"{path}#Close Checklist"),
                {(blocker.code, blocker.file) for blocker in blockers},
            )
            self.assertIn("incomplete_close_checklist", {blocker.code for blocker in blockers})

    def test_final_report_validation_requires_reusable_lessons_section(self):
        missing_section = COMPLETE_FINAL_REPORT.replace(
            "\n## Reusable Lessons\n\nNo reusable lesson.\n",
            "",
        )
        with markdown(missing_section) as path:
            blockers = documents.validate("final-report", path, {"outcome": "positive"})
            self.assertIn(
                ("missing_final_report_section", f"{path}#Reusable Lessons"),
                {(blocker.code, blocker.file) for blocker in blockers},
            )

        empty_section = COMPLETE_FINAL_REPORT.replace("No reusable lesson.", "")
        with markdown(empty_section) as path:
            blockers = documents.validate("final-report", path, {"outcome": "positive"})
            self.assertIn(
                ("missing_final_report_section", f"{path}#Reusable Lessons"),
                {(blocker.code, blocker.file) for blocker in blockers},
            )

    def test_final_report_validation_blocks_missing_file(self):
        blockers = documents.validate("final-report", Path("/tmp/rdl-missing-final-report.md"))
        self.assertEqual([blocker.code for blocker in blockers], ["missing_final_report"])

    def test_progress_required_sections_validate(self):
        with markdown(COMPLETE_PROGRESS) as path:
            self.assertEqual(documents.validate("progress", path), [])

        with markdown(COMPLETE_PROGRESS.replace("## Open Questions", "## Questions")) as path:
            codes = [blocker.code for blocker in documents.validate("progress", path)]
            self.assertIn("missing_progress_section", codes)


class markdown:
    def __init__(self, text):
        self.text = text
        self.tempdir = None
        self.path = None

    def __enter__(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "doc.md"
        self.path.write_text(self.text, encoding="utf-8")
        return self.path

    def __exit__(self, exc_type, exc, tb):
        self.tempdir.cleanup()


COMPLETE_REVIEW = """# Review

Reviewer: fixture
Review Mode: manual
Review Scope: current round
Artifacts Reviewed: prompt, evidence, decision
Verdict: PASS
Decision Reviewed: continue
Evidence Reviewed: fixture evidence
Blocking Evidence Gaps: none
Implementation Findings: none
Evaluation Integrity Findings: acceptable
Overclaim Risks: bounded
Fresh Evidence: yes
Staleness Signal: none
Direction Reuse Risk: low
Readiness Level: ready
Recommended Decision: continue

## Returned Review Findings

- none

## Accepted Corrections and Resolutions

none
"""


COMPLETE_DECISION = """# Decision

Decision: continue
Closes: claim
Evidence: E1 fixture evidence
Uncertainty: bounded
What this rules out: unsupported alternatives
What remains unknown: later work
Direction changed: no
Prior directions checked: fixture prior directions checked
Stall response: no staleness signal
Recommended next loop: none
Next smallest step: continue same mode
"""


COMPLETE_FINAL_REPORT = """# Final Report

## Outcome

positive

## Claim or Capability Closed

fixture claim

## Evidence Cited

E1 fixture evidence.

## Missing Evidence and Confounders

No blocking missing evidence.

## Negative, Null, or Inconclusive Results

None beyond the selected close outcome.

## Open Questions

No blocking open questions remain.

## Deferred Items

Deferred fixture follow-up has a revisit trigger.

## Directions Tried And Stall Responses

No repeated directions.

## Reusable Lessons

No reusable lesson.

## Close Checklist

- [x] Final decision is positive, negative, or inconclusive.
"""


COMPLETE_PROGRESS = """# Progress

## Active

| Item | Mode | Claim or Capability | Blocking? | Next Review Trigger |
|---|---|---|---|---|

## Completed

| Item | Decision | Evidence | Round |
|---|---|---|---|

## Blocked

| Item | Reason | Needed Evidence or Input | Decision Impact |
|---|---|---|---|

## Deferred

| Item | Reason | Revisit Trigger |
|---|---|---|

## Open Questions

| Question | Owner | Blocking? | Resolution |
|---|---|---|---|

## Directions Tried

| Direction | Rounds | Outcome | Why Not Repeat |
|---|---|---|---|

## Staleness Watch

| Signal | Evidence | Response |
|---|---|---|
"""


if __name__ == "__main__":
    unittest.main()

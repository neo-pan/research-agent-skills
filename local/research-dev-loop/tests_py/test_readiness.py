import tempfile
import unittest
from pathlib import Path

from rdl import readiness
from rdl.session import SessionStore

from rdl_test_support import (
    REPEATED_NEGATIVE_EVIDENCE,
    complete_build_round,
    complete_decision,
    complete_final_report,
    complete_research_round,
    complete_review,
    create_session,
    set_current_round,
)


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

    def test_build_round_accepts_indented_verification_evidence_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), session_id="b1", mode="build")
            complete_build_round(session_dir, verification=False)
            evidence_file = session_dir / "rounds" / "001" / "evidence.md"
            evidence_file.write_text(evidence_file.read_text(encoding="utf-8") + "\n  Verification evidence: tests passed\n", encoding="utf-8")

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current")}
            self.assertNotIn("missing_verification_evidence", codes)

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

    def test_close_positive_blocks_unresolved_blocking_open_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = close_ready_session(Path(tmp), "close-positive", "positive")
            (session_dir / "progress.md").write_text(PROGRESS_WITH_BLOCKING_OPEN_QUESTION, encoding="utf-8")

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current")}
            self.assertIn("unresolved_blocking_open_questions", codes)

    def test_doctor_current_routes_close_decisions_through_close_readiness(self):
        cases = (
            ("close-positive", "positive", "unresolved_blocking_open_questions"),
            ("close-negative", "negative", "unresolved_blocking_open_questions"),
            ("close-inconclusive", "inconclusive", "missing_final_report_section"),
        )
        for decision, outcome, expected_code in cases:
            with self.subTest(decision=decision):
                with tempfile.TemporaryDirectory() as tmp:
                    session_dir = close_ready_session(Path(tmp), decision, outcome)
                    if outcome == "inconclusive":
                        (session_dir / "final-report.md").write_text("# Final Report\n\n## Outcome\n\ninconclusive\n", encoding="utf-8")
                    else:
                        (session_dir / "progress.md").write_text(PROGRESS_WITH_BLOCKING_OPEN_QUESTION, encoding="utf-8")

                    codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current")}

                    self.assertIn(expected_code, codes)

    def test_close_positive_reads_generated_blocking_question_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = close_ready_session(Path(tmp), "close-positive", "positive")
            (session_dir / "progress.md").write_text(PROGRESS_WITH_BLOCKING_QUESTION_MARK_HEADER, encoding="utf-8")

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current")}
            self.assertIn("unresolved_blocking_open_questions", codes)

    def test_close_inconclusive_allows_unresolved_blocking_open_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = close_ready_session(Path(tmp), "close-inconclusive", "inconclusive")
            (session_dir / "progress.md").write_text(PROGRESS_WITH_BLOCKING_OPEN_QUESTION, encoding="utf-8")

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current")}
            self.assertNotIn("unresolved_blocking_open_questions", codes)

    def test_advance_allows_review_blocking_evidence_gaps_for_close_inconclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = close_ready_session(Path(tmp), "close-inconclusive", "inconclusive")
            review_file = session_dir / "rounds" / "001" / "review.md"
            review_file.write_text(review_file.read_text(encoding="utf-8").replace("Blocking Evidence Gaps: none", "Blocking Evidence Gaps: unresolved blockers"), encoding="utf-8")

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "advance")}
            self.assertNotIn("blocked_review", codes)

    def test_close_blocks_incomplete_deferred_item_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = close_ready_session(Path(tmp), "close-positive", "positive")
            (session_dir / "progress.md").write_text(PROGRESS_WITH_INCOMPLETE_DEFERRED_ITEM, encoding="utf-8")

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current")}
            self.assertIn("incomplete_deferred_items", codes)

    def test_repeated_negative_evidence_after_prior_continue_requires_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = repeated_negative_session(Path(tmp), acknowledged=False)

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current")}
            self.assertIn("unacknowledged_repeated_negative_evidence", codes)

    def test_repeated_negative_evidence_acknowledgement_in_decision_or_progress_allows_close(self):
        for acknowledged_in in ("decision", "progress"):
            with self.subTest(acknowledged_in=acknowledged_in):
                with tempfile.TemporaryDirectory() as tmp:
                    session_dir = repeated_negative_session(Path(tmp), acknowledged=False)
                    if acknowledged_in == "decision":
                        decision_file = session_dir / "rounds" / "002" / "decision.md"
                        decision_file.write_text(decision_file.read_text(encoding="utf-8") + "\nRepeated negative evidence acknowledged.\n", encoding="utf-8")
                    else:
                        progress_file = session_dir / "progress.md"
                        progress_file.write_text(progress_file.read_text(encoding="utf-8") + "\ncontinue justified after repeated failure.\n", encoding="utf-8")

                    codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current")}
                    self.assertNotIn("unacknowledged_repeated_negative_evidence", codes)

    def test_advance_blocks_blocked_review_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), mode="research")
            complete_research_round(session_dir, decision="continue")
            review_file = session_dir / "rounds" / "001" / "review.md"
            review_file.write_text(review_file.read_text(encoding="utf-8").replace("Verdict: PASS", "Verdict: BLOCKED"), encoding="utf-8")

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "advance")}
            self.assertIn("blocked_review", codes)

    def test_advance_blocks_inconclusive_review_without_close_inconclusive_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), mode="research")
            complete_research_round(session_dir, decision="continue")
            review_file = session_dir / "rounds" / "001" / "review.md"
            review_file.write_text(review_file.read_text(encoding="utf-8").replace("Verdict: PASS", "Verdict: INCONCLUSIVE"), encoding="utf-8")

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "advance")}
            self.assertIn("inconclusive_review_verdict", codes)

    def test_advance_blocks_nonempty_blocking_evidence_gaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), mode="research")
            complete_research_round(session_dir, decision="continue")
            review_file = session_dir / "rounds" / "001" / "review.md"
            review_file.write_text(review_file.read_text(encoding="utf-8").replace("Blocking Evidence Gaps: none", "Blocking Evidence Gaps: missing baseline"), encoding="utf-8")

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "advance")}
            self.assertIn("blocked_review", codes)

    def test_advance_accepts_non_blocking_gap_phrases(self):
        for phrase in ("no blocking evidence gaps", "not applicable"):
            with self.subTest(phrase=phrase):
                with tempfile.TemporaryDirectory() as tmp:
                    session_dir = create_session(Path(tmp), mode="research")
                    complete_research_round(session_dir, decision="continue")
                    review_file = session_dir / "rounds" / "001" / "review.md"
                    review_file.write_text(review_file.read_text(encoding="utf-8").replace("Blocking Evidence Gaps: none", f"Blocking Evidence Gaps: {phrase}"), encoding="utf-8")

                    codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "advance")}
                    self.assertNotIn("blocked_review", codes)

    def test_advance_blocks_stale_continue_without_stall_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), mode="research")
            complete_research_round(session_dir, decision="continue")
            round_dir = session_dir / "rounds" / "001"
            review_file = round_dir / "review.md"
            decision_file = round_dir / "decision.md"
            review_file.write_text(
                review_file.read_text(encoding="utf-8")
                .replace("Fresh Evidence: yes", "Fresh Evidence: no")
                .replace("Staleness Signal: none", "Staleness Signal: repeated")
                .replace("Direction Reuse Risk: low", "Direction Reuse Risk: high"),
                encoding="utf-8",
            )
            decision_file.write_text(
                decision_file.read_text(encoding="utf-8").replace("Stall response: no staleness signal", "Stall response:"),
                encoding="utf-8",
            )

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "advance")}
            self.assertIn("missing_staleness_response", codes)

    def test_doctor_current_blocks_stale_continue_without_stall_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), mode="research")
            complete_research_round(session_dir, decision="continue")
            round_dir = session_dir / "rounds" / "001"
            review_file = round_dir / "review.md"
            decision_file = round_dir / "decision.md"
            review_file.write_text(
                review_file.read_text(encoding="utf-8")
                .replace("Fresh Evidence: yes", "Fresh Evidence: no")
                .replace("Staleness Signal: none", "Staleness Signal: repeated"),
                encoding="utf-8",
            )
            decision_file.write_text(
                decision_file.read_text(encoding="utf-8").replace("Stall response: no staleness signal", "Stall response:"),
                encoding="utf-8",
            )

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "doctor-current")}
            self.assertIn("missing_staleness_response", codes)

    def test_advance_allows_stale_continue_with_stall_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            session_dir = create_session(Path(tmp), mode="research")
            complete_research_round(session_dir, decision="continue")
            review_file = session_dir / "rounds" / "001" / "review.md"
            review_file.write_text(
                review_file.read_text(encoding="utf-8")
                .replace("Fresh Evidence: yes", "Fresh Evidence: mixed")
                .replace("Staleness Signal: none", "Staleness Signal: possible"),
                encoding="utf-8",
            )

            codes = {blocker.code for blocker in readiness.check(SessionStore(Path(tmp)).active_session(), "advance")}
            self.assertNotIn("missing_staleness_response", codes)


def close_ready_session(root: Path, decision: str, outcome: str) -> Path:
    session_dir = create_session(root, mode="research")
    complete_research_round(session_dir, decision=decision)
    (session_dir / "final-report.md").write_text(complete_final_report(outcome), encoding="utf-8")
    return session_dir


def repeated_negative_session(root: Path, acknowledged: bool) -> Path:
    session_dir = create_session(root, mode="research")
    complete_research_round(session_dir, decision="continue")
    round_dir = set_current_round(session_dir, 2)
    (round_dir / "evidence.md").write_text(REPEATED_NEGATIVE_EVIDENCE, encoding="utf-8")
    (round_dir / "interpretation.md").write_text("# Interpretation\n\nRepeated failure still matters.\n", encoding="utf-8")
    (round_dir / "review.md").write_text(complete_review("close-negative"), encoding="utf-8")
    decision_text = complete_decision("close-negative", "claim")
    if acknowledged:
        decision_text += "\nRepeated negative evidence acknowledged.\n"
    (round_dir / "decision.md").write_text(decision_text, encoding="utf-8")
    (session_dir / "final-report.md").write_text(complete_final_report("negative"), encoding="utf-8")
    return session_dir


PROGRESS_WITH_BLOCKING_OPEN_QUESTION = """# Progress

## Active

none

## Completed

none

## Blocked

none

## Deferred

| Item | Reason | Revisit Trigger |
|---|---|---|

## Open Questions

| Question | Owner | Blocking | Resolution |
|---|---|---|---|
| unresolved risk | team | yes | - |

## Directions Tried

none

## Staleness Watch

none
"""


PROGRESS_WITH_BLOCKING_QUESTION_MARK_HEADER = """# Progress

## Active

none

## Completed

none

## Blocked

none

## Deferred

| Item | Reason | Revisit Trigger |
|---|---|---|

## Open Questions

| Question | Owner | Blocking? | Resolution |
|---|---|---|---|
| unresolved risk | team | yes | - |

## Directions Tried

none

## Staleness Watch

none
"""


PROGRESS_WITH_INCOMPLETE_DEFERRED_ITEM = """# Progress

## Active

none

## Completed

none

## Blocked

none

## Deferred

| Item | Reason | Revisit Trigger |
|---|---|---|
| follow-up | - | |

## Open Questions

| Question | Owner | Blocking | Resolution |
|---|---|---|---|

## Directions Tried

none

## Staleness Watch

none
"""


if __name__ == "__main__":
    unittest.main()

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
    REPEATED_NEGATIVE_EVIDENCE,
    assert_gate_details_compatible,
    bind_review_subject,
    complete_decision,
    complete_final_report,
    complete_research_round,
    complete_review,
    create_session,
    refresh_integrity,
    set_current_round,
)


class CliCloseTests(unittest.TestCase):
    def test_close_accepts_bound_review_across_summary_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "positive")
            bind_review_subject(session_dir, "close")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "positive", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["details"]["gate"]["semantic"]["subject_binding"]["status"], "matched")
            self.assertNotIn("semantic_review_subject_stale", result["warnings"])

    def test_closed_session_preserves_bound_close_review_for_terminal_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "negative")
            recorded_digest = bind_review_subject(session_dir, "close")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "negative", "--json"]), 0)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--session-path", str(session_dir), "--json"]), 0)

            doctor_result = json.loads(stdout.getvalue())
            binding = doctor_result["details"]["gate"]["semantic"]["subject_binding"]
            self.assertEqual(binding["status"], "matched")
            self.assertEqual(binding["recorded_digest"], recorded_digest)
            self.assertEqual(binding["current_digest"], recorded_digest)
            self.assertNotIn("semantic_review_subject_stale", doctor_result["warnings"])

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(
                    main(["review", "--pack", "--for", "close", "--session-path", str(session_dir), "--json"]),
                    0,
                )

            review_result = json.loads(stdout.getvalue())
            self.assertEqual(review_result["details"]["review_pack"]["subject_digest"], recorded_digest)

    def test_terminal_subject_drift_requires_restoration_not_review_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "negative")
            bind_review_subject(session_dir, "close")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "negative", "--json"]), 0)

            evidence = session_dir / "rounds" / "001" / "evidence.md"
            evidence.write_text(evidence.read_text(encoding="utf-8") + "\nChanged after closure.\n", encoding="utf-8")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--session-path", str(session_dir), "--json"]), 2)

            result = json.loads(stdout.getvalue())
            blocker = next(item for item in result["blockers"] if item["code"] == "semantic_review_subject_stale")
            self.assertEqual(
                blocker["message"],
                "Closed session records no longer match the semantic review that authorized closure.",
            )
            self.assertEqual(
                blocker["next_action"],
                "Restore the reviewed terminal records or start a new reviewed session; do not rewrite review.md.",
            )

    def test_terminal_human_ledger_append_remains_in_review_subject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "negative")
            bind_review_subject(session_dir, "close")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "negative", "--json"]), 0)

            ledger = session_dir / "decision-ledger.md"
            ledger.write_text(ledger.read_text(encoding="utf-8") + "\nHuman terminal note.\n", encoding="utf-8")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--session-path", str(session_dir), "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertIn("semantic_review_subject_stale", {item["code"] for item in result["blockers"]})

    def test_terminal_close_ledger_field_tampering_is_stale(self):
        cases = (
            ("- Evidence: ", "- Evidence: HUMAN TAMPER"),
            ("- Uncertainty: ", "- Uncertainty: HUMAN TAMPER"),
            ("- Remaining unknown: ", "- Remaining unknown: HUMAN TAMPER"),
            ("- Closes: ", "- Closes: capability"),
            ("- Round: ", "- Round: 002"),
            ("- Closed at UTC: ", "- Closed at UTC: 2026-07-12T00:00:00Z"),
        )
        for prefix, replacement in cases:
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                session_dir = close_ready_session(root, "negative")
                bind_review_subject(session_dir, "close")

                stdout = StringIO()
                with change_dir(root), redirect_stdout(stdout):
                    self.assertEqual(main(["close", "negative", "--json"]), 0)

                ledger = session_dir / "decision-ledger.md"
                lines = ledger.read_text(encoding="utf-8").splitlines()
                ledger.write_text(
                    "\n".join(replacement if line.startswith(prefix) else line for line in lines) + "\n",
                    encoding="utf-8",
                )
                refresh_integrity(session_dir)

                stdout = StringIO()
                with change_dir(root), redirect_stdout(stdout):
                    self.assertEqual(main(["doctor", "--session-path", str(session_dir), "--json"]), 2)

                result = json.loads(stdout.getvalue())
                self.assertIn("semantic_review_subject_stale", {item["code"] for item in result["blockers"]})

    def test_removing_markers_and_format_cannot_downgrade_current_close_to_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "negative")
            decision = session_dir / "rounds" / "001" / "decision.md"
            decision.write_text(
                decision.read_text(encoding="utf-8").replace(
                    "Next smallest step: continue same mode",
                    "Next smallest step: none; session is closed-negative",
                ),
                encoding="utf-8",
            )
            refresh_integrity(session_dir)
            bind_review_subject(session_dir, "close")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "negative", "--json"]), 0)

            ledger = session_dir / "decision-ledger.md"
            marker_lines = {
                "<!-- rdl:transition kind=close start -->",
                "<!-- rdl:transition kind=close end -->",
                "- Record Format: rdl-close-v2",
            }
            ledger.write_text(
                "\n".join(line for line in ledger.read_text(encoding="utf-8").splitlines() if line not in marker_lines)
                + "\n",
                encoding="utf-8",
            )
            refresh_integrity(session_dir)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["doctor", "--session-path", str(session_dir), "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertIn("semantic_review_subject_stale", {item["code"] for item in result["blockers"]})

    def test_close_blocks_when_bound_final_report_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "positive")
            bind_review_subject(session_dir, "close")
            final_report = session_dir / "final-report.md"
            final_report.write_text(
                final_report.read_text(encoding="utf-8").replace("fixture claim", "changed claim scope"),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "positive", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertIn("semantic_review_subject_stale", {blocker["code"] for blocker in result["blockers"]})
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")

    def test_close_json_closes_supported_outcomes(self):
        for outcome in ("positive", "negative", "inconclusive"):
            with self.subTest(outcome=outcome):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    session_dir = close_ready_session(root, outcome)

                    stdout = StringIO()
                    with change_dir(root), redirect_stdout(stdout):
                        self.assertEqual(main(["close", outcome, "--json"]), 0)

                    result = json.loads(stdout.getvalue())
                    self.assertEqual(result["status"], "ok")
                    self.assertEqual(result["action"], "close")
                    self.assertEqual(result["session_id"], "close_ok")
                    self.assertEqual(result["mode"], "research")
                    self.assertEqual(result["phase"], "complete")
                    self.assertEqual(result["round"], 1)
                    self.assertEqual(result["next_action"], f"closed-{outcome}")
                    self.assertNotIn("summary_needs_update", result["warnings"])
                    assert_gate_details_compatible(self, result["details"]["gate"])
                    self.assertEqual(result["details"]["gate"]["summary"]["summary_status"], "up_to_date")

                    state = store.read_json(session_dir / "state.json")
                    self.assertEqual(state["status"], f"closed-{outcome}")
                    self.assertEqual(state["phase"], "complete")
                    progress = (session_dir / "progress.md").read_text(encoding="utf-8")
                    self.assertIn("<!-- rdl:summary section=Completed start -->", progress)
                    self.assertIn(f"| round-001 | close-{outcome} | fixture evidence | 001 |", progress)
                    ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
                    self.assertIn("## Session Summary Refresh", ledger)
                    self.assertIn("<!-- rdl:transition kind=close start -->", ledger)
                    self.assertIn("## Session Closed", ledger)
                    self.assertIn("- Record Format: rdl-close-v2", ledger)
                    self.assertIn(f"- Decision: close-{outcome}", ledger)
                    self.assertIn("- Evidence: fixture evidence", ledger)
                    self.assertIn("- Uncertainty: bounded", ledger)
                    self.assertIn("- Remaining unknown: later work", ledger)
                    self.assertIn(f"- Next smallest step: none; session is closed-{outcome}", ledger)
                    self.assertIn("<!-- rdl:transition kind=close end -->", ledger)
                    manifest = store.read_json(session_dir / "integrity.json")
                    entries = {entry["path"]: entry for entry in manifest["entries"]}
                    self.assertIn("final-report.md", entries)
                    self.assertEqual(entries["rounds/001/gate-report.json"]["policy"], "cli_owned")
                    self.assertEqual(entries["rounds/001/gate.md"]["policy"], "cli_owned")
                    progress_entry = next(entry for entry in manifest["entries"] if entry["path"] == "progress.md")
                    self.assertEqual(progress_entry["sha256"], integrity.file_sha256(session_dir / "progress.md"))
                    gate_report = store.read_json(session_dir / "rounds" / "001" / "gate-report.json")
                    self.assertEqual(gate_report["action"], "close")
                    self.assertEqual(gate_report["close_record_format"], "rdl-close-v2")
                    self.assertEqual(gate_report["status"], "needs_attention")
                    self.assertEqual(gate_report["details"]["semantic"]["adapter"], "manual")
                    self.assertNotIn("round_content_ahead_of_state_phase", gate_report["warnings"])
                    self.assertIn(f"Action: close", (session_dir / "rounds" / "001" / "gate.md").read_text(encoding="utf-8"))

    def test_close_json_blocks_for_missing_final_report_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "close-positive")
            refresh_integrity(session_dir)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "positive", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["details"]["gate"]["gate_status"], "blocked")
            self.assertIn("missing_final_report", {blocker["code"] for blocker in result["blockers"]})
            gate_codes = {finding["code"] for finding in result["details"]["gate"]["findings"]}
            self.assertIn("missing_final_report", gate_codes)
            self.assertEqual(result["next_action"], "complete close records")
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")
            self.assertNotIn("## Session Closed", (session_dir / "decision-ledger.md").read_text(encoding="utf-8"))

    def test_close_json_blocks_for_incomplete_final_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "positive")
            report = session_dir / "final-report.md"
            report.write_text(report.read_text(encoding="utf-8").replace("fixture claim", ""), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "positive", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertIn("missing_final_report_section", {blocker["code"] for blocker in result["blockers"]})
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")

    def test_close_json_blocks_for_decision_outcome_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "negative")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "positive", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            codes = {blocker["code"] for blocker in result["blockers"]}
            self.assertIn("invalid_close_decision", codes)
            self.assertIn("close_outcome_mismatch", codes)
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")

    def test_close_json_blocks_positive_for_unresolved_blocking_open_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "positive")
            (session_dir / "progress.md").write_text(PROGRESS_WITH_BLOCKING_OPEN_QUESTION, encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "positive", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertIn("unresolved_blocking_open_questions", {blocker["code"] for blocker in result["blockers"]})
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")

    def test_close_json_allows_inconclusive_with_unresolved_blocking_open_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "inconclusive")
            (session_dir / "progress.md").write_text(PROGRESS_WITH_BLOCKING_OPEN_QUESTION, encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "inconclusive", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["next_action"], "closed-inconclusive")
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "closed-inconclusive")

    def test_close_json_infers_outcome_from_current_close_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "positive")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["next_action"], "closed-positive")
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "closed-positive")

    def test_close_json_surfaces_repeated_negative_evidence_as_review_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = repeated_negative_close_session(root, acknowledged=False)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "negative", "--json"]), 0)

            result = json.loads(stdout.getvalue())
            self.assertNotIn("unacknowledged_repeated_negative_evidence", {blocker["code"] for blocker in result["blockers"]})
            signal_codes = set(result["details"]["gate"]["semantic"]["review_pack"]["agent_review_signal_codes"])
            self.assertIn("repeated_negative_evidence_after_continue", signal_codes)
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "closed-negative")

    def test_close_json_errors_when_integrity_refresh_fails_after_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "positive")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["memory", "--write", "--json"]), 0)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                with patch("rdl.commands.integrity.refresh", side_effect=ValueError("refresh failed")):
                    self.assertEqual(main(["close", "positive", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "close")
            self.assertEqual(result["blockers"][0]["code"], "integrity_refresh_failed")
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "closed-positive")

    def test_close_json_errors_when_gate_report_write_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "positive")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout), patch("rdl.commands.gate_reports.write", side_effect=OSError("disk full")):
                self.assertEqual(main(["close", "positive", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "close")
            self.assertEqual(result["blockers"][0]["code"], "gate_report_write_failed")
            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["status"], "active")
            self.assertEqual(state["phase"], "plan")
            self.assertNotIn("## Session Closed", (session_dir / "decision-ledger.md").read_text(encoding="utf-8"))

    def test_close_invalid_outcome_returns_structured_error(self):
        stdout = StringIO()
        with redirect_stdout(stdout), redirect_stderr(StringIO()):
            self.assertEqual(main(["close", "unknown", "--json"]), 1)

        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["blockers"][0]["code"], "invalid_close_outcome")

    def test_close_missing_outcome_returns_structured_error(self):
        stdout = StringIO()
        with redirect_stdout(stdout), redirect_stderr(StringIO()):
            self.assertEqual(main(["close", "--json"]), 1)

        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["blockers"][0]["code"], "missing_close_outcome")


def close_ready_session(root: Path, outcome: str) -> Path:
    session_dir = create_session(root, "close_ok")
    complete_research_round(session_dir, f"close-{outcome}")
    (session_dir / "final-report.md").write_text(complete_final_report(outcome), encoding="utf-8")
    integrity.refresh(SessionStore(root).active_session())
    return session_dir


def repeated_negative_close_session(root: Path, acknowledged: bool) -> Path:
    session_dir = create_session(root, "close_negative")
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
    integrity.refresh(SessionStore(root).active_session())
    return session_dir


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


PROGRESS_WITH_BLOCKING_OPEN_QUESTION = """# Progress

## Active

none

## Completed

| Item | Decision | Evidence | Round |
|---|---|---|---|

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

| Direction | Rounds | Outcome | Why Not Repeat |
|---|---|---|---|

## Staleness Watch

| Signal | Evidence | Response |
|---|---|---|
"""


if __name__ == "__main__":
    unittest.main()

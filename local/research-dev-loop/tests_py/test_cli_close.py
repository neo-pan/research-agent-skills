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
    complete_decision,
    complete_final_report,
    complete_research_round,
    complete_review,
    create_session,
    refresh_integrity,
    set_current_round,
)


class CliCloseTests(unittest.TestCase):
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

                    state = store.read_json(session_dir / "state.json")
                    self.assertEqual(state["status"], f"closed-{outcome}")
                    self.assertEqual(state["phase"], "complete")
                    ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
                    self.assertIn("## Session Closed", ledger)
                    self.assertIn(f"- Decision: close-{outcome}", ledger)
                    self.assertIn("- Evidence: fixture evidence", ledger)
                    self.assertIn("- Uncertainty: bounded", ledger)
                    self.assertIn("- Remaining unknown: later work", ledger)
                    self.assertIn("- Next smallest step: continue same mode", ledger)
                    manifest = store.read_json(session_dir / "integrity.json")
                    self.assertIn("final-report.md", {entry["path"] for entry in manifest["entries"]})

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

    def test_close_json_blocks_unacknowledged_repeated_negative_evidence_after_prior_continue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = repeated_negative_close_session(root, acknowledged=False)

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                self.assertEqual(main(["close", "negative", "--json"]), 2)

            result = json.loads(stdout.getvalue())
            self.assertIn("unacknowledged_repeated_negative_evidence", {blocker["code"] for blocker in result["blockers"]})
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")

    def test_close_json_errors_when_integrity_refresh_fails_after_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "positive")

            stdout = StringIO()
            with change_dir(root), redirect_stdout(stdout):
                with patch("rdl.commands.integrity.refresh", side_effect=ValueError("refresh failed")):
                    self.assertEqual(main(["close", "positive", "--json"]), 1)

            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["action"], "close")
            self.assertEqual(result["blockers"][0]["code"], "integrity_refresh_failed")
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "closed-positive")

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


if __name__ == "__main__":
    unittest.main()

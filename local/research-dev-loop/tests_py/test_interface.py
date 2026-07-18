from __future__ import annotations

import unittest
import argparse

from rdl.cli import build_parser
from rdl.model import RdlError

from rdl_test_support import START, project, review_result, routine_delta, run_cli


class InterfaceTests(unittest.TestCase):
    def test_seven_command_cli_and_routine_round(self):
        with project() as (root, _engine):
            code, start = run_cli(root, ["start", "--input", "-", "--session-id", "routine"], START)
            self.assertEqual((code, start["state_version"]), (0, 1))

            code, handoff = run_cli(root, ["handoff"])
            self.assertEqual((code, handoff["session_id"]), (0, "routine"))

            code, applied = run_cli(root, ["apply", "--input", "-"], routine_delta())
            self.assertEqual((code, applied["transition_readiness"]), (0, "ready"))
            self.assertEqual(applied["assigned_ids"]["artifacts"]["report"], "A000001")
            self.assertEqual(applied["assigned_ids"]["evidence"]["result"], "E000001")
            self.assertNotIn("changed_state", applied)
            self.assertNotIn("declared_risk", applied)

            code, advanced = run_cli(root, ["next", "--expected-state-version", "2"])
            self.assertEqual((code, advanced["round"], advanced["state_version"]), (0, 2, 3))
            code, doctor = run_cli(root, ["doctor", "--diagnostics"])
            self.assertEqual((code, doctor["status"]), (0, "ok"))

    def test_material_review_binding_and_scientific_close(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="material", request=START)
            applied = engine.execute(
                "apply", session_id="material", request=routine_delta(transition="close", outcome="positive", risk="material")
            )
            self.assertEqual(applied["effective_risk"], "material")
            self.assertEqual(applied["transition_readiness"], "needs_review")
            pack = engine.execute("review", session_id="material", action="close")
            self.assertEqual(pack["subject_digest"], applied["review_subject_digest"])
            bound = engine.execute("apply", session_id="material", request=review_result(2, pack["subject_digest"]))
            self.assertEqual(bound["transition_readiness"], "ready")
            self.assertFalse(bound["review_required"])
            with self.assertRaisesRegex(RdlError, "does not require review"):
                engine.execute("review", session_id="material", action="close")
            closed = engine.execute(
                "close", session_id="material", expected_state_version=3, outcome="positive"
            )
            self.assertEqual(closed["transition_readiness"], "terminal")
            self.assertEqual(engine.execute("handoff", session_id="material")["session_status"], "closed-positive")

    def test_abandoned_close_bypasses_round_readiness(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="abandoned", request=START)
            receipt = engine.execute(
                "close", session_id="abandoned", expected_state_version=1, outcome="abandoned", reason="external input unavailable"
            )
            self.assertEqual(receipt["effective_risk"], "routine")
            generation = engine.repository.current_generation("abandoned")
            report = (generation / "final-report.md").read_text(encoding="utf-8")
            self.assertIn("Scientific outcome claimed: none", report)

    def test_invalid_input_is_machine_readable(self):
        with project() as (root, _engine):
            code, result = run_cli(root, ["start", "--input", "-"] , {"mode": "research"})
            self.assertEqual(code, 1)
            self.assertEqual(result["code"], "invalid_type")

    def test_only_seven_commands_are_accepted(self):
        with project() as (root, _engine):
            code, result = run_cli(root, ["status"])
            self.assertEqual(code, 1)
            self.assertEqual(result["code"], "parser_error")
            subparsers = next(action for action in build_parser()._actions if isinstance(action, argparse._SubParsersAction))
            self.assertEqual(set(subparsers.choices), {"start", "handoff", "apply", "review", "next", "close", "doctor"})

    def test_progress_and_factors_null_delete_only_at_map_level(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="maps", request=START)
            first = {
                "expected_state_version": 1,
                "risk": "routine",
                "progress_updates": {"p": {"status": "active", "summary": "work", "blocking": False}},
                "factor_updates": {"f": {"category": "environment", "value": "fixture"}},
            }
            engine.execute("apply", session_id="maps", request=first)
            engine.execute(
                "apply",
                session_id="maps",
                request={"expected_state_version": 2, "risk": "routine", "progress_updates": {"p": None}, "factor_updates": {"f": None}},
            )
            state = engine.repository.load("maps")
            self.assertEqual((state["progress"], state["factors"]), ({}, {}))
            with self.assertRaises(RdlError):
                engine.execute(
                    "apply",
                    session_id="maps",
                    request={"expected_state_version": 3, "risk": "routine", "interpretation": None},
                )

    def test_handoff_and_review_budgets_block_without_truncation(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="budget", request=START)
            huge = "x" * 32000
            delta = routine_delta(risk="material")
            delta["progress_updates"]["fixture"]["summary"] = huge
            engine.execute("apply", session_id="budget", request=delta)
            with self.assertRaisesRegex(RdlError, "hard limit") as handoff_error:
                engine.execute("handoff", session_id="budget")
            self.assertIn("sections", handoff_error.exception.details)
            with self.assertRaisesRegex(RdlError, "hard limit") as review_error:
                engine.execute("review", session_id="budget", action="next")
            self.assertIn("sections", review_error.exception.details)


if __name__ == "__main__":
    unittest.main()

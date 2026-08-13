from __future__ import annotations

import json
import unittest
import argparse

from rdl import rendering
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

    def test_post_next_handoff_exposes_the_accepted_action_and_durable_protocol(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="takeover", request=START)
            delta = routine_delta(risk="material")
            instruction = (
                "Run the focused CLI matrix and freeze its receipt; completion requires the focused and existing "
                "integration suites to pass, then record a next decision for the independent terminal audit."
            )
            delta["decision"]["subject"] = "Advance to the bounded implementation and verification phase."
            delta["decision"]["next_step"] = instruction
            delta["progress_updates"].update(
                {
                    "phase-2-implementation": {
                        "status": "active",
                        "summary": "Implement and verify the bounded CLI contract.",
                        "blocking": False,
                    },
                    "phase-3-terminal-audit": {
                        "status": "open_question",
                        "summary": "Run the independent terminal audit before close.",
                        "blocking": False,
                    },
                    "phase-4-portability": {
                        "status": "deferred",
                        "summary": "Retain the portability boundary for a later supported environment.",
                        "blocking": False,
                        "reason": "The current task supports Linux and WSL only.",
                        "revisit_trigger": "A supported macOS or Windows execution environment becomes available.",
                    },
                }
            )
            applied = engine.execute("apply", session_id="takeover", request=delta)
            review = engine.execute("review", session_id="takeover", action="next")
            self.assertEqual(review["subject_digest"], applied["review_subject_digest"])
            bound = engine.execute(
                "apply",
                session_id="takeover",
                request=review_result(2, review["subject_digest"], action="next"),
            )
            self.assertEqual(bound["transition_readiness"], "ready")
            engine.execute("next", session_id="takeover", expected_state_version=3)

            handoff = engine.execute("handoff", session_id="takeover")

            self.assertEqual(
                handoff["current_action"],
                {
                    "source_round": 1,
                    "instruction": instruction,
                    "decision_subject": "Advance to the bounded implementation and verification phase.",
                    "evidence": [
                        {
                            "id": "E000001",
                            "claim": "fixture claim",
                            "summary": "the direct fixture check passed",
                            "bearing": "supports",
                            "strength": "strong",
                            "artifact_refs": ["A000001"],
                            "uncertainty": "one bounded fixture",
                        }
                    ],
                    "write_through_gate": (
                        "Execute the instruction, freeze the smallest sufficient receipt or snapshot, then apply "
                        "the current round's evidence, interpretation, and decision before any transition."
                    ),
                    "remaining_protocol": {
                        "success_criteria": START["mission"]["success_criteria"],
                        "unfinished_progress": [
                            {
                                "key": "phase-2-implementation",
                                "status": "active",
                                "summary": "Implement and verify the bounded CLI contract.",
                                "blocking": False,
                            },
                            {
                                "key": "phase-3-terminal-audit",
                                "status": "open_question",
                                "summary": "Run the independent terminal audit before close.",
                                "blocking": False,
                            },
                            {
                                "key": "phase-4-portability",
                                "status": "deferred",
                                "summary": "Retain the portability boundary for a later supported environment.",
                                "blocking": False,
                                "reason": "The current task supports Linux and WSL only.",
                                "revisit_trigger": (
                                    "A supported macOS or Windows execution environment becomes available."
                                ),
                            },
                        ],
                    },
                },
            )
            self.assertEqual([item["id"] for item in handoff["artifacts"]], ["A000001"])

            engine.execute(
                "apply",
                session_id="takeover",
                request={
                    "expected_state_version": 4,
                    "risk": "routine",
                    "factor_updates": {
                        "large-context": {
                            "category": "projection",
                            "value": "x" * 32000,
                        }
                    },
                },
            )
            compact = engine.execute("handoff", session_id="takeover")
            self.assertEqual(compact["projection_profile"], "compact_manifest")
            self.assertEqual(
                compact["canonical_state"]["read_sections"][:5],
                ["/mission", "/progress", "/factors", "/rounds/0", "/rounds/1"],
            )
            self.assertIn("current_action", compact["omitted_inline_sections"])

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
            handoff = engine.execute("handoff", session_id="material")
            self.assertEqual(handoff["session_status"], "closed-positive")
            self.assertNotIn("current_action", handoff)
            self.assertNotIn("next_step", handoff["round"]["decision"])
            self.assertEqual(
                handoff["terminal_summary"],
                {
                    "outcome": "positive",
                    "state_version": 4,
                    "closed_at_utc": engine.repository.load("material")["updated_at_utc"],
                    "final_review_binding": {
                        "action": "close",
                        "review_id": "R000001",
                        "subject_digest": applied["review_subject_digest"],
                    },
                    "unfinished_progress": [],
                    "historical_next_step": {
                        "status": "pre_close_instruction",
                        "text": "run the next bounded check",
                    },
                },
            )

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

    def test_all_terminal_outcomes_have_a_bounded_manifest(self):
        for outcome in ("positive", "negative", "inconclusive", "abandoned"):
            with self.subTest(outcome=outcome), project() as (_root, engine):
                start = json.loads(json.dumps(START))
                start["mission"]["scope"] = ["x" * 32000]
                session_id = f"terminal-{outcome}"
                engine.execute("start", session_id=session_id, request=start)
                if outcome == "abandoned":
                    engine.execute(
                        "close",
                        session_id=session_id,
                        expected_state_version=1,
                        outcome=outcome,
                        reason="the bounded fixture is complete",
                    )
                else:
                    applied = engine.execute(
                        "apply",
                        session_id=session_id,
                        request=routine_delta(
                            transition="close",
                            outcome=outcome,
                            risk="material",
                        ),
                    )
                    engine.execute(
                        "apply",
                        session_id=session_id,
                        request=review_result(2, applied["review_subject_digest"]),
                    )
                    engine.execute(
                        "close",
                        session_id=session_id,
                        expected_state_version=3,
                        outcome=outcome,
                    )

                handoff = engine.execute("handoff", session_id=session_id)
                self.assertEqual(handoff["projection_profile"], "compact_manifest")
                self.assertEqual(handoff["session_status"], f"closed-{outcome}" if outcome != "abandoned" else outcome)
                self.assertEqual(handoff["terminal_summary"]["outcome"], outcome)
                self.assertEqual(handoff["terminal_summary"]["state_version"], handoff["state_version"])
                self.assertNotIn("current_action", handoff)
                if outcome == "abandoned":
                    self.assertIsNone(handoff["terminal_summary"]["final_review_binding"])
                    self.assertIsNone(handoff["terminal_summary"]["historical_next_step"])
                else:
                    self.assertEqual(handoff["terminal_summary"]["final_review_binding"]["action"], "close")
                    self.assertEqual(
                        handoff["terminal_summary"]["historical_next_step"]["status"],
                        "pre_close_instruction",
                    )
                self.assertEqual(
                    handoff["canonical_state"]["final_report_path"],
                    f".rdl/.store/{session_id}/{handoff['state_version']}/final-report.md",
                )
                self.assertLessEqual(
                    len(json.dumps(handoff, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()),
                    24 * 1024,
                )

    def test_non_abandoned_close_requires_active_progress_reconciliation(self):
        with project() as (_root, engine):
            session_id = "active-close"
            engine.execute("start", session_id=session_id, request=START)
            delta = routine_delta(transition="close", outcome="positive", risk="material")
            delta["progress_updates"]["pending"] = {
                "status": "active",
                "summary": "work remains",
                "blocking": False,
            }

            applied = engine.execute("apply", session_id=session_id, request=delta)

            self.assertEqual(applied["transition_readiness"], "blocked")
            self.assertNotIn("review_subject_digest", applied)
            with self.assertRaisesRegex(RdlError, "not ready") as close_error:
                engine.execute(
                    "close",
                    session_id=session_id,
                    expected_state_version=2,
                    outcome="positive",
                )
            self.assertIn("unreconciled_active_progress", close_error.exception.details["blockers"])
            self.assertEqual(engine.repository.load(session_id)["state_version"], 2)

    def test_reconciled_and_non_active_progress_can_close(self):
        for status in ("completed", "deferred", "open_question"):
            with self.subTest(status=status), project() as (_root, engine):
                session_id = f"reconciled-{status}"
                engine.execute("start", session_id=session_id, request=START)
                delta = routine_delta(transition="close", outcome="inconclusive", risk="material")
                progress = {
                    "status": status,
                    "summary": f"work is explicitly {status}",
                    "blocking": False,
                }
                if status == "deferred":
                    progress.update({"reason": "environment unavailable", "revisit_trigger": "environment returns"})
                delta["progress_updates"]["pending"] = progress
                applied = engine.execute("apply", session_id=session_id, request=delta)
                engine.execute(
                    "apply",
                    session_id=session_id,
                    request=review_result(2, applied["review_subject_digest"]),
                )

                engine.execute(
                    "close",
                    session_id=session_id,
                    expected_state_version=3,
                    outcome="inconclusive",
                )

                handoff = engine.execute("handoff", session_id=session_id)
                expected = [] if status == "completed" else [
                    {"key": "pending", "status": status, "blocking": False}
                ]
                self.assertEqual(handoff["terminal_summary"]["unfinished_progress"], expected)

    def test_next_and_abandoned_allow_active_progress(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="active-next", request=START)
            delta = routine_delta(transition="next", risk="material")
            delta["progress_updates"]["pending"] = {
                "status": "active",
                "summary": "work remains for the next round",
                "blocking": False,
            }
            applied = engine.execute("apply", session_id="active-next", request=delta)
            self.assertEqual(applied["transition_readiness"], "needs_review")

        with project() as (_root, engine):
            engine.execute("start", session_id="active-abandoned", request=START)
            delta = routine_delta()
            delta.pop("decision")
            delta["progress_updates"]["pending"] = {
                "status": "active",
                "summary": "work remains",
                "blocking": False,
            }
            engine.execute("apply", session_id="active-abandoned", request=delta)
            engine.execute(
                "close",
                session_id="active-abandoned",
                expected_state_version=2,
                outcome="abandoned",
                reason="external input unavailable",
            )
            handoff = engine.execute("handoff", session_id="active-abandoned")
            self.assertEqual(
                handoff["terminal_summary"]["unfinished_progress"],
                [{"key": "pending", "status": "active", "blocking": False}],
            )

    def test_terminal_summary_lists_only_unfinished_progress(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="terminal-progress", request=START)
            delta = routine_delta(transition="close", outcome="inconclusive", risk="material")
            delta["progress_updates"].update(
                {
                    "question": {"status": "open_question", "summary": "work remains uncertain", "blocking": False},
                    "deferred": {
                        "status": "deferred",
                        "summary": "portable execution remains deferred",
                        "blocking": False,
                        "reason": "environment unavailable",
                        "revisit_trigger": "supported environment becomes available",
                    },
                    "historical": {
                        "status": "direction_tried",
                        "summary": "the rejected path is historical",
                        "blocking": False,
                    },
                }
            )
            applied = engine.execute("apply", session_id="terminal-progress", request=delta)
            engine.execute(
                "apply",
                session_id="terminal-progress",
                request=review_result(2, applied["review_subject_digest"]),
            )
            engine.execute(
                "close",
                session_id="terminal-progress",
                expected_state_version=3,
                outcome="inconclusive",
            )

            handoff = engine.execute("handoff", session_id="terminal-progress")
            self.assertEqual(
                handoff["terminal_summary"]["unfinished_progress"],
                [
                    {"key": "deferred", "status": "deferred", "blocking": False},
                    {"key": "question", "status": "open_question", "blocking": False},
                ],
            )
            report = (
                engine.repository.current_generation("terminal-progress") / "final-report.md"
            ).read_text(encoding="utf-8")
            self.assertIn("## Terminal Summary", report)
            self.assertIn("deferred: deferred", report)
            self.assertIn("question: open_question", report)
            self.assertNotIn("historical: direction_tried", report)
            self.assertIn("pre_close_instruction: run the next bounded check", report)

    def test_terminal_compact_summary_references_unbounded_details_and_close_succeeds(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="terminal-compact-details", request=START)
            delta = routine_delta(transition="close", outcome="inconclusive", risk="material")
            delta["decision"]["next_step"] = "x" * 28000
            delta["progress_updates"].update(
                {
                    f"pending-{index}": {
                        "status": "open_question",
                        "summary": f"bounded unfinished item {index}",
                        "blocking": False,
                    }
                    for index in range(12)
                }
            )
            applied = engine.execute("apply", session_id="terminal-compact-details", request=delta)
            pack = engine.execute("review", session_id="terminal-compact-details", action="close")
            self.assertLessEqual(
                len(json.dumps(pack, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()),
                rendering.REVIEW_HARD_BYTES,
            )
            engine.execute(
                "apply",
                session_id="terminal-compact-details",
                request=review_result(2, applied["review_subject_digest"]),
            )

            closed = engine.execute(
                "close",
                session_id="terminal-compact-details",
                expected_state_version=3,
                outcome="inconclusive",
            )
            handoff = engine.execute("handoff", session_id="terminal-compact-details")

            self.assertEqual(closed["transition_readiness"], "terminal")
            self.assertEqual(handoff["projection_profile"], "compact_manifest")
            self.assertLessEqual(
                len(json.dumps(handoff, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()),
                rendering.HANDOFF_HARD_BYTES,
            )
            self.assertEqual(
                handoff["terminal_summary"]["unfinished_progress"],
                {
                    "count": 12,
                    "status_counts": {"open_question": 12},
                    "read_section": "/progress",
                },
            )
            self.assertEqual(
                handoff["terminal_summary"]["historical_next_step"],
                {
                    "status": "pre_close_instruction",
                    "read_section": "/rounds/0/decision/next_step",
                },
            )

    def test_abandoned_after_close_review_has_no_final_review_binding(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="abandoned-after-review", request=START)
            applied = engine.execute(
                "apply",
                session_id="abandoned-after-review",
                request=routine_delta(transition="close", outcome="positive", risk="material"),
            )
            engine.execute(
                "apply",
                session_id="abandoned-after-review",
                request=review_result(2, applied["review_subject_digest"]),
            )
            engine.execute(
                "close",
                session_id="abandoned-after-review",
                expected_state_version=3,
                outcome="abandoned",
                reason="the bounded task was superseded",
            )

            state = engine.repository.load("abandoned-after-review")
            handoff = engine.execute("handoff", session_id="abandoned-after-review")
            self.assertEqual(len(state["rounds"][0]["review_history"]), 1)
            self.assertEqual(handoff["terminal_summary"]["outcome"], "abandoned")
            self.assertIsNone(handoff["terminal_summary"]["final_review_binding"])

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

    def test_oversized_handoff_returns_bounded_manifest(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="budget", request=START)
            huge = "x" * 32000
            delta = routine_delta(risk="material")
            delta["progress_updates"]["fixture"]["summary"] = huge
            engine.execute("apply", session_id="budget", request=delta)

            handoff = engine.execute("handoff", session_id="budget")
            state = engine.repository.load("budget")
            encoded = json.dumps(handoff, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()

            self.assertLessEqual(len(encoded), 24 * 1024)
            self.assertEqual(handoff["projection_profile"], "compact_manifest")
            self.assertEqual(
                handoff["canonical_state"],
                {
                    "path": ".rdl/.store/budget/2/state.json",
                    "state_digest": state["state_digest"],
                    "read_sections": [
                        "/mission",
                        "/progress",
                        "/factors",
                        "/rounds/0",
                        "/evidence",
                        "/artifacts",
                        "/events",
                    ],
                },
            )
            self.assertEqual(
                handoff["omitted_inline_sections"],
                ["mission", "progress", "factors", "round", "artifacts"],
            )
            self.assertEqual(
                handoff["warnings"],
                ["handoff_full_inline_over_budget", "review_pack_soft_budget_exceeded"],
            )
            self.assertGreater(handoff["accounting"]["full_inline_size_bytes"], 24 * 1024)
            self.assertEqual(handoff["accounting"]["inline_limit_bytes"], 24 * 1024)

    def test_observed_near_limit_handoff_shape_uses_the_manifest(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="observed-budget", request=START)
            delta = routine_delta()
            delta["factor_updates"] = {
                "padding": {
                    "category": "projection",
                    "value": "x" * 22976,
                }
            }
            engine.execute("apply", session_id="observed-budget", request=delta)

            handoff = engine.execute("handoff", session_id="observed-budget")

            self.assertGreater(
                handoff["accounting"]["full_inline_size_bytes"],
                rendering.HANDOFF_HARD_BYTES,
            )
            self.assertEqual(handoff["projection_profile"], "compact_manifest")

    def test_handoff_budget_uses_final_utf8_json_bytes(self):
        cases = (
            ("ascii", "x" * 8000, "full_inline"),
            ("chinese", "研" * 8000, "compact_manifest"),
            ("escaped", '"\\' * 6000, "compact_manifest"),
        )
        for session_id, value, expected_profile in cases:
            with self.subTest(session_id=session_id), project() as (_root, engine):
                engine.execute("start", session_id=session_id, request=START)
                delta = routine_delta()
                delta["factor_updates"] = {
                    "padding": {
                        "category": "projection",
                        "value": value,
                    }
                }
                engine.execute("apply", session_id=session_id, request=delta)

                handoff = engine.execute("handoff", session_id=session_id)
                profile = handoff.get("projection_profile", "full_inline")

                self.assertEqual(profile, expected_profile)

    def test_doctor_reports_handoff_projection_diagnostics(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="projection-doctor", request=START)
            delta = routine_delta()
            delta["progress_updates"]["fixture"]["summary"] = "x" * 32000
            engine.execute("apply", session_id="projection-doctor", request=delta)

            doctor = engine.execute("doctor", session_id="projection-doctor", diagnostics=True)
            handoff = doctor["diagnostics"]["projections"]["handoff"]

            self.assertEqual(doctor["status"], "ok")
            self.assertEqual(doctor["findings"], [])
            self.assertEqual(handoff["profile"], "compact_manifest")
            self.assertGreater(handoff["full_inline_size_bytes"], 24 * 1024)
            self.assertLessEqual(handoff["final_size_bytes"], 24 * 1024)
            self.assertTrue(handoff["optimization_target_exceeded"])
            self.assertIn("progress", handoff["sections"])

    def test_review_budget_is_absent_without_a_decision_and_quiet_for_a_small_two_round_flow(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="review-budget-small", request=START)
            handoff = engine.execute("handoff", session_id="review-budget-small")
            self.assertNotIn("review_budget", handoff)

            checkpoint = engine.execute(
                "apply",
                session_id="review-budget-small",
                request={"expected_state_version": 1, "risk": "routine"},
            )
            self.assertNotIn("review_budget", checkpoint)

            applied = engine.execute(
                "apply",
                session_id="review-budget-small",
                request=routine_delta(version=2, risk="material"),
            )
            handoff = engine.execute("handoff", session_id="review-budget-small")
            pack = engine.execute("review", session_id="review-budget-small", action="next")
            expected = {
                "action": "next",
                "size_bytes": len(json.dumps(pack, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()),
                "soft_limit_bytes": 32 * 1024,
                "hard_limit_bytes": 48 * 1024,
                "soft_limit_exceeded": False,
                "hard_limit_exceeded": False,
            }
            self.assertEqual(applied["review_budget"], expected)
            self.assertEqual(handoff["review_budget"], expected)
            self.assertEqual(applied["warnings"], [])
            self.assertEqual(handoff["warnings"], [])

            engine.execute(
                "apply",
                session_id="review-budget-small",
                request=review_result(3, pack["subject_digest"], action="next"),
            )
            engine.execute("next", session_id="review-budget-small", expected_state_version=4)
            second_round = engine.execute("handoff", session_id="review-budget-small")
            self.assertNotIn("review_budget", second_round)
            self.assertEqual(second_round["warnings"], [])

    def test_review_soft_budget_warns_without_blocking_the_pack(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="review-soft-budget", request=START)
            delta = routine_delta(risk="material")
            delta["progress_updates"]["fixture"]["summary"] = "x" * 34000
            applied = engine.execute("apply", session_id="review-soft-budget", request=delta)

            doctor = engine.execute("doctor", session_id="review-soft-budget", diagnostics=True)
            handoff = engine.execute("handoff", session_id="review-soft-budget")
            review = engine.execute("review", session_id="review-soft-budget", action="next")
            review_size = len(
                json.dumps(review, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
            )

            self.assertEqual(doctor["status"], "ok")
            self.assertEqual(
                [finding["code"] for finding in doctor["findings"]],
                ["review_pack_soft_budget_exceeded"],
            )
            self.assertGreater(review_size, 32 * 1024)
            self.assertLessEqual(review_size, 48 * 1024)
            self.assertEqual(
                doctor["diagnostics"]["projections"]["review"]["size_bytes"],
                review_size,
            )
            expected = {
                "action": "next",
                "size_bytes": review_size,
                "soft_limit_bytes": 32 * 1024,
                "hard_limit_bytes": 48 * 1024,
                "soft_limit_exceeded": True,
                "hard_limit_exceeded": False,
            }
            self.assertEqual(applied["review_budget"], expected)
            self.assertEqual(handoff["review_budget"], expected)
            self.assertEqual(applied["warnings"], ["review_pack_soft_budget_exceeded"])
            self.assertEqual(
                handoff["warnings"],
                ["handoff_full_inline_over_budget", "review_pack_soft_budget_exceeded"],
            )

    def test_review_hard_budget_fails_closed_while_the_session_remains_recoverable(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="review-hard-budget", request=START)
            delta = routine_delta(risk="material")
            delta["progress_updates"]["fixture"]["summary"] = "x" * 52000
            applied = engine.execute("apply", session_id="review-hard-budget", request=delta)

            doctor = engine.execute("doctor", session_id="review-hard-budget", diagnostics=True)
            handoff = engine.execute("handoff", session_id="review-hard-budget")
            with self.assertRaisesRegex(RdlError, "hard limit") as review_error:
                engine.execute("review", session_id="review-hard-budget", action="next")

            self.assertEqual(doctor["status"], "blocked")
            self.assertEqual(
                [finding["code"] for finding in doctor["findings"]],
                ["review_pack_over_budget"],
            )
            self.assertTrue(doctor["diagnostics"]["projections"]["review"]["hard_limit_exceeded"])
            self.assertEqual(review_error.exception.details["limit_bytes"], 48 * 1024)
            self.assertEqual(handoff["projection_profile"], "compact_manifest")
            expected = {
                "action": "next",
                "size_bytes": doctor["diagnostics"]["projections"]["review"]["size_bytes"],
                "soft_limit_bytes": 32 * 1024,
                "hard_limit_bytes": 48 * 1024,
                "soft_limit_exceeded": True,
                "hard_limit_exceeded": True,
            }
            self.assertEqual(applied["review_budget"], expected)
            self.assertEqual(handoff["review_budget"], expected)
            self.assertEqual(applied["warnings"], ["review_pack_over_budget"])
            self.assertEqual(
                handoff["warnings"],
                ["handoff_full_inline_over_budget", "review_pack_over_budget"],
            )
            self.assertEqual(engine.repository.load("review-hard-budget")["state_version"], 2)

    def test_handoff_preserves_full_mission_and_lifecycle_closure(self):
        with project() as (root, engine):
            engine.execute("start", session_id="handoff-lifecycle", request=START)
            initial = routine_delta(transition="close", outcome="inconclusive", risk="material")
            initial["artifacts"]["report"]["stability"] = "live"
            engine.execute("apply", session_id="handoff-lifecycle", request=initial)
            (root / "artifacts" / "report.json").write_text('{"changed":true}\n', encoding="utf-8")
            engine.execute(
                "apply",
                session_id="handoff-lifecycle",
                request={
                    "expected_state_version": 2,
                    "risk": "routine",
                    "artifact_resolutions": {
                        "retire": {
                            "artifact_ref": "A000001",
                            "kind": "retired",
                            "reason": "The running report is historical only.",
                        }
                    },
                },
            )
            handoff = engine.execute("handoff", session_id="handoff-lifecycle")
            self.assertEqual(handoff["mission"], START["mission"])
            self.assertEqual(handoff["round"]["evidence"][0]["artifact_refs"], ["A000001"])
            self.assertEqual([item["id"] for item in handoff["artifacts"]], ["A000001"])
            artifact = handoff["artifacts"][0]
            self.assertEqual(
                set(artifact),
                {"id", "kind", "path", "stability", "integrity", "verifier", "resolution"},
            )
            self.assertEqual(artifact["resolution"]["observed"]["status"], "drifted")

    def test_representative_three_resolution_handoff_stays_within_frozen_budget(self):
        self.assertEqual(
            (
                rendering.HANDOFF_SOFT_BYTES,
                rendering.HANDOFF_HARD_BYTES,
                rendering.REVIEW_SOFT_BYTES,
                rendering.REVIEW_HARD_BYTES,
            ),
            (20 * 1024, 24 * 1024, 32 * 1024, 48 * 1024),
        )
        with project() as (root, engine):
            actual_session_detail = (
                "counterevidence, confounders, staleness, memory fidelity, artifact integrity, "
                "verifier scope, uncertainty, and decision consistency remain explicit; "
            )
            mission = {
                "objective": "Determine whether a bounded installer workflow remains correct across three reviewed phases.",
                "scope": [
                    f"phase {index}: preserve the complete command, receipt, and uncertainty record; "
                    + actual_session_detail * 3
                    for index in range(1, 7)
                ],
                "out_of_scope": ["network package acquisition", "production deployment", "unrelated installer redesign"],
                "success_criteria": [
                    "each phase has direct evidence and a frozen receipt",
                    "lifecycle reconciliation remains explicit and review-bound",
                    "terminal replay is byte-for-byte stable",
                ],
                "invariants": ["do not edit canonical state", "do not hide drift", "preserve negative observations"],
                "abort_criteria": ["the projection exceeds its hard budget", "artifact identity cannot be verified"],
            }
            engine.execute("start", session_id="representative-budget", request={"mode": "build", "mission": mission})
            artifacts = {}
            evidence = {}
            progress = {}
            for index in range(1, 4):
                path = root / "artifacts" / f"running-{index}.json"
                path.write_text(json.dumps({"phase": index, "status": "running"}) + "\n", encoding="utf-8")
                artifacts[f"running-{index}"] = {
                    "kind": "receipt",
                    "path": f"artifacts/running-{index}.json",
                    "description": f"phase {index} running receipt",
                    "stability": "live",
                    "verifier": {
                        "name": "bounded-command-check",
                        "status": "passed",
                        "summary": f"phase {index} command and receipt shape were checked",
                    },
                }
                evidence[f"phase-{index}"] = {
                    "claim": f"phase {index} completed its bounded mechanics check",
                    "summary": f"the direct phase {index} receipt records the command, result, and bounded caveat",
                    "bearing": "supports",
                    "strength": "moderate",
                    "artifact_refs": [f"running-{index}"],
                    "uncertainty": "semantic adequacy remains reviewer-owned",
                }
                progress[f"phase-{index}"] = {
                    "status": "completed",
                    "summary": f"phase {index} mechanics and receipt checks completed; "
                    + actual_session_detail * 15,
                    "blocking": False,
                    "evidence_refs": [f"phase-{index}"],
                }
            engine.execute(
                "apply",
                session_id="representative-budget",
                request={
                    "expected_state_version": 1,
                    "risk": "material",
                    "artifacts": artifacts,
                    "evidence": evidence,
                    "progress_updates": progress,
                    "factor_updates": {
                        "environment": {
                            "category": "execution",
                            "value": "isolated local fixture with deterministic receipts",
                            "uncertainty": "does not establish production portability",
                        }
                    },
                    "interpretation": {
                        "shows": ["the bounded mechanics checks completed"],
                        "does_not_show": ["production deployment correctness"],
                        "uncertainty": ["the running receipts will continue changing"],
                        "implications": ["freeze replacements before terminal review"],
                    },
                    "decision": {
                        "kind": "accept",
                        "subject": "the bounded installer mechanics are ready for an inconclusive scoped close",
                        "evidence_refs": [f"phase-{index}" for index in range(1, 4)],
                        "uncertainty": "the fixture does not establish broader deployment behavior",
                        "remaining_unknowns": ["production portability", "external package manager behavior"],
                        "next_step": "close this bounded session after lifecycle reconciliation and review",
                        "recommended_transition": "close",
                        "close_outcome": "inconclusive",
                    },
                },
            )
            replacements = {}
            resolutions = {}
            for index in range(1, 4):
                (root / "artifacts" / f"running-{index}.json").write_text(
                    json.dumps({"phase": index, "status": "finished"}) + "\n", encoding="utf-8"
                )
                (root / "artifacts" / f"snapshot-{index}.json").write_text(
                    json.dumps({"phase": index, "status": "finished"}) + "\n", encoding="utf-8"
                )
                replacements[f"snapshot-{index}"] = {
                    "kind": "receipt",
                    "path": f"artifacts/snapshot-{index}.json",
                    "description": f"frozen phase {index} receipt",
                    "stability": "snapshot",
                }
                resolutions[f"supersede-{index}"] = {
                    "artifact_ref": f"A{index:06d}",
                    "kind": "superseded",
                    "replacement_ref": f"snapshot-{index}",
                    "reason": f"Bind phase {index} to its frozen final receipt.",
                }
            engine.execute(
                "apply",
                session_id="representative-budget",
                request={
                    "expected_state_version": 2,
                    "risk": "material",
                    "artifacts": replacements,
                    "artifact_resolutions": resolutions,
                },
            )
            handoff = engine.execute("handoff", session_id="representative-budget")
            review = engine.execute("review", session_id="representative-budget", action="close")
            handoff_size = len(json.dumps(handoff, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode())
            review_size = len(json.dumps(review, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode())
            self.assertGreater(handoff_size, 14 * 1024)
            self.assertLess(handoff_size, rendering.HANDOFF_SOFT_BYTES)
            self.assertLess(review_size, rendering.REVIEW_HARD_BYTES)

            engine.execute(
                "apply",
                session_id="representative-budget",
                request={
                    "expected_state_version": 3,
                    "risk": "routine",
                    "factor_updates": {
                        "maximum-existing-session-detail": {
                            "category": "projection",
                            "value": actual_session_detail * 50,
                            "uncertainty": "synthetic maximum derived from the longest observed session sections",
                        }
                    },
                },
            )
            maximum = engine.execute("handoff", session_id="representative-budget")
            maximum_size = len(
                json.dumps(maximum, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
            )
            self.assertGreater(maximum_size, rendering.HANDOFF_SOFT_BYTES)
            self.assertLess(maximum_size, rendering.HANDOFF_HARD_BYTES)
            self.assertEqual(maximum["warnings"], [])


if __name__ == "__main__":
    unittest.main()

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
            (rendering.HANDOFF_SOFT_BYTES, rendering.HANDOFF_HARD_BYTES, rendering.REVIEW_HARD_BYTES),
            (20 * 1024, 24 * 1024, 30 * 1024),
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
            self.assertIn("handoff_soft_budget_exceeded", maximum["warnings"])


if __name__ == "__main__":
    unittest.main()

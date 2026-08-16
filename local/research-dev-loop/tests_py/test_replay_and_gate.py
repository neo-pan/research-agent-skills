from __future__ import annotations

import json
import unittest
from hashlib import sha256
from unittest.mock import patch
from pathlib import Path

from rdl import rendering
from rdl.engine import RdlEngine
from rdl.model import RdlError
from rdl.store import Repository

from rdl_test_support import START, project, review_result, routine_delta


class ReplayAndGateTests(unittest.TestCase):
    def test_transition_projection_failure_leaves_the_current_generation_unchanged(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="projection-preflight", request=START)
            engine.execute("apply", session_id="projection-preflight", request=routine_delta())
            pointer_before = engine.repository.pointer("projection-preflight").readlink()
            generations_before = sorted(
                path.name
                for path in engine.repository.generation("projection-preflight", 2).parent.iterdir()
                if path.is_dir()
            )

            with patch("rdl.rendering.HANDOFF_HARD_BYTES", 1):
                with self.assertRaisesRegex(RdlError, "hard limit"):
                    engine.execute(
                        "next",
                        session_id="projection-preflight",
                        expected_state_version=2,
                    )

            state = engine.repository.load("projection-preflight")
            self.assertEqual(state["state_version"], 2)
            self.assertEqual(engine.repository.pointer("projection-preflight").readlink(), pointer_before)
            self.assertEqual(
                sorted(
                    path.name
                    for path in engine.repository.generation("projection-preflight", 2).parent.iterdir()
                    if path.is_dir()
                ),
                generations_before,
            )

    def test_close_projection_failure_leaves_the_reviewed_generation_unchanged(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="close-projection-preflight", request=START)
            applied = engine.execute(
                "apply",
                session_id="close-projection-preflight",
                request=routine_delta(transition="close", outcome="positive", material=True),
            )
            engine.execute(
                "apply",
                session_id="close-projection-preflight",
                request=review_result(2, applied["review_subject_digest"]),
            )
            pointer_before = engine.repository.pointer("close-projection-preflight").readlink()
            generations_before = sorted(
                path.name
                for path in engine.repository.generation("close-projection-preflight", 3).parent.iterdir()
                if path.is_dir()
            )

            with patch("rdl.rendering.HANDOFF_HARD_BYTES", 1):
                with self.assertRaisesRegex(RdlError, "hard limit"):
                    engine.execute(
                        "close",
                        session_id="close-projection-preflight",
                        expected_state_version=3,
                        outcome="positive",
                    )

            state = engine.repository.load("close-projection-preflight")
            self.assertEqual(state["state_version"], 3)
            self.assertEqual(engine.repository.pointer("close-projection-preflight").readlink(), pointer_before)
            self.assertEqual(
                sorted(
                    path.name
                    for path in engine.repository.generation("close-projection-preflight", 3).parent.iterdir()
                    if path.is_dir()
                ),
                generations_before,
            )

    def test_explicit_start_and_immediate_apply_replay_return_exact_receipt(self):
        with project() as (_root, engine):
            first = engine.execute("start", session_id="replay", request=START)
            self.assertEqual(engine.execute("start", session_id="replay", request=START), first)
            delta = routine_delta()
            applied = engine.execute("apply", session_id="replay", request=delta)
            self.assertEqual(engine.execute("apply", session_id="replay", request=delta), applied)

    def test_stale_caller_has_zero_writes(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="stale", request=START)
            engine.execute("apply", session_id="stale", request={"expected_state_version": 1})
            before = engine.repository.current_generation("stale")
            with self.assertRaisesRegex(RdlError, "stale"):
                engine.execute("next", session_id="stale", expected_state_version=1)
            self.assertEqual(engine.repository.current_generation("stale"), before)

    def test_terminal_replay_and_mutation_truth_table_has_zero_writes(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="terminal-matrix", request=START)
            applied = engine.execute(
                "apply",
                session_id="terminal-matrix",
                request=routine_delta(transition="close", outcome="positive", material=True),
            )
            engine.execute(
                "apply",
                session_id="terminal-matrix",
                request=review_result(2, applied["review_subject_digest"]),
            )
            closed = engine.execute(
                "close", session_id="terminal-matrix", expected_state_version=3, outcome="positive"
            )
            pointer = engine.repository.current_generation("terminal-matrix")
            generations = engine.execute("doctor", session_id="terminal-matrix", diagnostics=True)["diagnostics"]["generations"]
            self.assertEqual(
                engine.execute("close", session_id="terminal-matrix", expected_state_version=3, outcome="positive"),
                closed,
            )
            probes = (
                ("apply", {"request": {"expected_state_version": 4}}, "terminal_session"),
                ("next", {"expected_state_version": 4}, "terminal_session"),
                ("close", {"expected_state_version": 4, "outcome": "positive"}, "terminal_session"),
                ("apply", {"request": {"expected_state_version": 2}}, "state_version_conflict"),
                ("next", {"expected_state_version": 2}, "state_version_conflict"),
                ("close", {"expected_state_version": 2, "outcome": "negative"}, "state_version_conflict"),
            )
            for command, kwargs, expected_code in probes:
                with self.subTest(command=command, expected_code=expected_code):
                    with self.assertRaises(RdlError) as error:
                        engine.execute(command, session_id="terminal-matrix", **kwargs)
                    self.assertEqual(error.exception.code, expected_code)
                    self.assertEqual(engine.repository.current_generation("terminal-matrix"), pointer)
                    self.assertEqual(engine.repository.load("terminal-matrix")["state_version"], 4)
                    self.assertEqual(
                        engine.execute("doctor", session_id="terminal-matrix", diagnostics=True)["diagnostics"]["generations"],
                        generations,
                    )

    def test_structural_material_upgrade(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="upgrade", request=START)
            receipt = engine.execute(
                "apply", session_id="upgrade", request=routine_delta(transition="next") | {"decision": routine_delta()["decision"] | {"kind": "pivot"}}
            )
            self.assertEqual(receipt["effective_risk"], "material")
            self.assertEqual(receipt["risk_upgrade_reasons"], ["decision:pivot"])
            self.assertEqual(receipt["transition_readiness"], "needs_review")

    def test_scientific_close_is_always_material(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="close-upgrade", request=START)
            delta = routine_delta(transition="close", outcome="inconclusive")
            receipt = engine.execute("apply", session_id="close-upgrade", request=delta)
            self.assertEqual(receipt["effective_risk"], "material")
            self.assertEqual(receipt["risk_upgrade_reasons"], ["scientific_close:inconclusive"])
            self.assertEqual(receipt["transition_readiness"], "needs_review")

    def test_binding_only_apply_does_not_change_subject_digest(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="digest", request=START)
            applied = engine.execute("apply", session_id="digest", request=routine_delta(material=True))
            pack = engine.execute("review", session_id="digest", action="next")
            engine.execute("apply", session_id="digest", request=review_result(2, pack["subject_digest"], action="next"))
            state = engine.repository.load("digest")
            self.assertEqual(
                rendering.subject_digest(state, "next", []),
                applied["review_subject_digest"],
            )

    def test_accepted_blocking_finding_blocks_transition(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="finding", request=START)
            applied = engine.execute("apply", session_id="finding", request=routine_delta(material=True))
            result = review_result(2, applied["review_subject_digest"], action="next")
            result["review_result"]["findings"] = [{
                "severity": "blocking",
                "category": "evidence",
                "claim": "missing control",
                "required_resolution": "add the control",
                "disposition": "accepted",
                "rationale": "valid finding",
            }]
            bound = engine.execute("apply", session_id="finding", request=result)
            self.assertEqual(bound["transition_readiness"], "blocked")
            self.assertFalse(bound["review_required"])

    def test_one_evidence_free_correction_then_new_evidence_cycle(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="cycles", request=START)
            applied = engine.execute("apply", session_id="cycles", request=routine_delta(material=True))
            first = review_result(2, applied["review_subject_digest"], action="next")
            first["decision"] = routine_delta()["decision"] | {"subject": "corrected fixture claim", "evidence_refs": ["E000001"]}
            corrected = engine.execute("apply", session_id="cycles", request=first)
            self.assertEqual(corrected["transition_readiness"], "needs_review")

            second_pack = engine.execute("review", session_id="cycles", action="next")
            second = review_result(3, second_pack["subject_digest"], action="next")
            second["decision"] = first["decision"] | {"subject": "second text-only correction"}
            with self.assertRaisesRegex(RdlError, "second evidence-free"):
                engine.execute("apply", session_id="cycles", request=second)

            second["evidence"] = {
                "extra": {
                    "claim": "corrected fixture claim",
                    "summary": "new external evidence resolves the requested check",
                    "bearing": "supports",
                    "strength": "strong",
                    "artifact_refs": ["A000001"],
                    "uncertainty": "bounded fixture",
                }
            }
            second["decision"]["evidence_refs"] = ["E000001", "extra"]
            evidence_cycle = engine.execute("apply", session_id="cycles", request=second)
            self.assertEqual(evidence_cycle["transition_readiness"], "needs_review")
            third_pack = engine.execute("review", session_id="cycles", action="next")
            bound = engine.execute(
                "apply",
                session_id="cycles",
                request=review_result(4, third_pack["subject_digest"], action="next"),
            )
            self.assertEqual(bound["transition_readiness"], "ready")

    def test_review_pack_preserves_known_defect_material(self):
        claim = "the receipt proves end-to-end behavior"
        counterevidence = "the receipt checks shape only and cannot observe end-to-end behavior"
        with project() as (_root, engine):
            engine.execute("start", session_id="defect", request=START)
            delta = routine_delta(material=True)
            delta["evidence"]["result"]["claim"] = claim
            delta["evidence"]["counter"] = {
                "claim": claim,
                "summary": counterevidence,
                "bearing": "contradicts",
                "strength": "contradicted",
                "artifact_refs": ["report"],
                "uncertainty": "semantic adjudication remains reviewer-owned",
            }
            delta["progress_updates"]["fixture"]["summary"] = claim
            delta["decision"]["subject"] = claim
            delta["decision"]["evidence_refs"] = ["result", "counter"]
            engine.execute("apply", session_id="defect", request=delta)
            pack = engine.execute("review", session_id="defect", action="next")

            evidence = pack["round"]["evidence"]
            self.assertEqual([item["claim"] for item in evidence], [claim, claim])
            self.assertEqual([item["bearing"] for item in evidence], ["supports", "contradicts"])
            self.assertEqual(evidence[1]["summary"], counterevidence)
            self.assertEqual(pack["round"]["decision"]["evidence_refs"], ["E000001", "E000002"])
            artifact = pack["artifacts"][0]
            self.assertEqual(
                set(artifact),
                {"id", "kind", "path", "description", "size_bytes", "sha256"},
            )
            self.assertEqual(artifact["path"], "artifacts/report.json")
            self.assertEqual(pack["session"]["progress"]["fixture"]["summary"], claim)
            size = len(json.dumps(pack, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))
            self.assertLessEqual(size, rendering.REVIEW_HARD_BYTES)

    def test_review_pack_exposes_decisive_evidence_artifact_coverage_without_blocking(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="coverage", request=START)
            delta = routine_delta(material=True)
            delta["evidence"]["result"]["artifact_refs"] = []
            applied = engine.execute("apply", session_id="coverage", request=delta)
            self.assertEqual(applied["transition_readiness"], "needs_review")

            pack = engine.execute("review", session_id="coverage", action="next")

            self.assertEqual(
                pack["evidence_coverage"],
                [
                    {
                        "evidence_id": "E000001",
                        "claim": "fixture claim",
                        "artifact_refs": [],
                        "artifact_binding": "absent",
                    }
                ],
            )
            self.assertEqual(pack["prior_review_context"], [])
            self.assertEqual(pack["deterministic_findings"], [])

    def test_review_selection_includes_displayed_and_counterevidence_and_reports_omissions(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="selection", request=START)
            delta = routine_delta(material=True)
            delta["evidence"].update(
                {
                    "progress-only": {
                        "claim": "prior displayed support",
                        "summary": "displayed progress cites this support",
                        "bearing": "supports",
                        "strength": "moderate",
                        "artifact_refs": ["report"],
                        "uncertainty": "bounded fixture",
                    },
                    "counter": {
                        "claim": "counterevidence remains visible",
                        "summary": "the counter check disagrees",
                        "bearing": "contradicts",
                        "strength": "strong",
                        "artifact_refs": ["report"],
                        "uncertainty": "bounded fixture",
                    },
                    "context": {
                        "claim": "uncited context",
                        "summary": "background only",
                        "bearing": "context",
                        "strength": "weak",
                        "artifact_refs": [],
                        "uncertainty": "not cited",
                    },
                }
            )
            delta["progress_updates"]["fixture"]["evidence_refs"] = ["progress-only"]
            engine.execute("apply", session_id="selection", request=delta)

            pack = engine.execute("review", session_id="selection", action="next")

            self.assertEqual(
                [item["id"] for item in pack["round"]["evidence"]],
                ["E000001", "E000002", "E000003"],
            )
            self.assertEqual(
                pack["evidence_selection"],
                {
                    "selected_ids": ["E000001", "E000002", "E000003"],
                    "omitted_current_round_ids": ["E000004"],
                    "omitted_current_round_count": 1,
                },
            )

    def test_artifact_bytes_are_hidden_and_the_description_carries_bounded_content(self):
        with project() as (root, engine):
            engine.execute("start", session_id="artifact-visibility", request=START)
            delta = routine_delta(material=True)
            secret = "A000014 raw artifact body is not reviewer-visible"
            (root / "artifacts" / "report.json").write_text(secret, encoding="utf-8")
            first = engine.execute("apply", session_id="artifact-visibility", request=delta)
            pack = engine.execute("review", session_id="artifact-visibility", action="next")
            self.assertNotIn(secret, json.dumps(pack, ensure_ascii=False))
            self.assertEqual(pack["artifacts"][0]["sha256"], sha256(secret.encode("utf-8")).hexdigest())

            correction = review_result(2, first["review_subject_digest"], action="next", verdict="revise")
            correction["artifacts"] = {
                "prepared": {
                    "kind": "receipt",
                    "path": "artifacts/report.json",
                    "description": "A000015 decisive bounded description",
                }
            }
            correction["evidence"] = {
                "prepared": {
                    "claim": "bounded preparation is visible",
                    "summary": "the description carries the decisive bounded content",
                    "bearing": "supports",
                    "strength": "strong",
                    "artifact_refs": ["prepared"],
                    "uncertainty": "raw bytes remain hidden",
                }
            }
            correction["decision"] = delta["decision"] | {"evidence_refs": ["prepared"]}
            engine.execute("apply", session_id="artifact-visibility", request=correction)
            rebound = engine.execute("review", session_id="artifact-visibility", action="next")
            self.assertIn("A000015 decisive bounded description", json.dumps(rebound, ensure_ascii=False))
            self.assertNotIn(secret, json.dumps(rebound, ensure_ascii=False))

    def test_missing_selected_reference_is_a_deterministic_blocker(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="missing-review-ref", request=START)
            engine.execute("apply", session_id="missing-review-ref", request=routine_delta(material=True))
            state = engine.repository.load("missing-review-ref")
            state["progress"]["fixture"]["evidence_refs"] = ["E999999"]

            findings = rendering.missing_review_reference_findings(state, state["rounds"][0])

            self.assertEqual(
                findings,
                [
                    {
                        "code": "missing_review_reference",
                        "severity": "blocking",
                        "location": "E999999",
                        "message": "selected evidence reference is missing from canonical state",
                    }
                ],
            )

    def test_review_questions_are_action_specific_and_bind_the_accepted_action(self):
        with project() as (_root, engine):
            start = json.loads(json.dumps(START))
            start["mission"]["success_criteria"].append("unfinished work is explicit")
            engine.execute("start", session_id="action-questions", request=start)

            first = routine_delta(material=True)
            first["decision"]["next_step"] = (
                "Run the final bounded check; complete when its frozen receipt passes; "
                "retain the terminal projection phase."
            )
            applied = engine.execute("apply", session_id="action-questions", request=first)
            next_pack = engine.execute("review", session_id="action-questions", action="next")

            self.assertIsNone(next_pack["action_context"])
            self.assertTrue(any("action_context" in item for item in next_pack["reviewer_task"]["questions"]))
            self.assertFalse(any("success_criteria[" in item for item in next_pack["reviewer_task"]["questions"]))

            engine.execute(
                "apply",
                session_id="action-questions",
                request=review_result(2, applied["review_subject_digest"], action="next"),
            )
            engine.execute("next", session_id="action-questions", expected_state_version=3)
            second = engine.execute(
                "apply",
                session_id="action-questions",
                request=routine_delta(version=4, transition="close", outcome="positive", material=True),
            )
            close_pack = engine.execute("review", session_id="action-questions", action="close")

            self.assertEqual(second["review_subject_digest"], close_pack["subject_digest"])
            self.assertEqual(
                close_pack["action_context"],
                {
                    "source_round": 1,
                    "instruction": first["decision"]["next_step"],
                    "decision_subject": first["decision"]["subject"],
                },
            )
            questions = close_pack["reviewer_task"]["questions"]
            self.assertTrue(any("each mission.success_criteria item" in item for item in questions))
            self.assertTrue(any("project-review receipt" in item for item in questions))
            self.assertFalse(any("decision.next_step executable" in item for item in questions))

    def test_fresh_review_pack_preserves_same_round_prior_finding_adjudication(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="prior-finding", request=START)
            applied = engine.execute("apply", session_id="prior-finding", request=routine_delta(material=True))
            first = review_result(2, applied["review_subject_digest"], action="next", verdict="revise")
            finding = {
                "severity": "blocking",
                "category": "evidence",
                "claim": "the decision lacks an independent correction receipt",
                "required_resolution": "add direct correction evidence and narrow the claim",
                "disposition": "accepted",
                "rationale": "the requested evidence is material to the candidate transition",
            }
            first["review_result"]["findings"] = [finding]
            blocked = engine.execute("apply", session_id="prior-finding", request=first)
            self.assertEqual(blocked["transition_readiness"], "blocked")
            corrected = engine.execute(
                "apply",
                session_id="prior-finding",
                request={
                    "expected_state_version": 3,
                    "evidence": {
                        "correction": {
                            "claim": "the bounded correction has a direct receipt",
                            "summary": "the correction check passed against the frozen fixture",
                            "bearing": "supports",
                            "strength": "strong",
                            "artifact_refs": ["A000001"],
                            "uncertainty": "the receipt remains fixture-scoped",
                        }
                    },
                    "decision": {
                        "kind": "accept",
                        "subject": "the fixture-scoped correction is ready for the next bounded round",
                        "evidence_refs": ["E000001", "correction"],
                        "uncertainty": "production scale remains untested",
                        "remaining_unknowns": ["larger workloads"],
                        "next_step": "run the next bounded check",
                        "recommended_transition": "next",
                    },
                },
            )
            self.assertEqual(corrected["transition_readiness"], "needs_review")

            pack = engine.execute("review", session_id="prior-finding", action="next")

            self.assertEqual(
                pack["prior_review_context"],
                [
                    {
                        "review_id": "R000001",
                        "action": "next",
                        "subject_digest": applied["review_subject_digest"],
                        "verdict": "revise",
                        "recorded_version": 3,
                        "findings": [finding],
                    }
                ],
            )
            rebound = engine.execute(
                "apply",
                session_id="prior-finding",
                request=review_result(4, pack["subject_digest"], action="next"),
            )
            self.assertEqual(rebound["transition_readiness"], "ready")

    def test_prior_review_compaction_retains_latest_pass_and_later_findings(self):
        finding = {
            "severity": "note",
            "category": "scope",
            "claim": "retain this finding",
            "required_resolution": "keep the boundary visible",
            "disposition": "accepted",
            "rationale": "the boundary remains material",
        }
        history = [
            {"id": "R000001", "action": "close", "subject_digest": "1" * 64, "adapter": "test", "verdict": "revise", "recorded_version": 2, "findings": [finding]},
            {"id": "R000002", "action": "close", "subject_digest": "2" * 64, "adapter": "test", "verdict": "pass", "recorded_version": 3, "findings": []},
            {"id": "R000003", "action": "close", "subject_digest": "3" * 64, "adapter": "test", "verdict": "pass_with_notes", "recorded_version": 4, "findings": [finding]},
            {"id": "R000004", "action": "close", "subject_digest": "4" * 64, "adapter": "test", "verdict": "revise", "recorded_version": 5, "findings": [finding]},
        ]

        compact = rendering._compact_review_history(history)

        self.assertEqual([item["review_id"] for item in compact], ["R000003", "R000004"])

    def _closed_session(self, engine, session_id, *, abandoned=False):
        engine.execute("start", session_id=session_id, request=START)
        if abandoned:
            engine.execute("apply", session_id=session_id, request=routine_delta())
            engine.execute(
                "close",
                session_id=session_id,
                expected_state_version=2,
                outcome="abandoned",
                reason="the bounded fixture is no longer reachable",
            )
            return
        delta = routine_delta(transition="close", outcome="positive", material=True)
        applied = engine.execute("apply", session_id=session_id, request=delta)
        engine.execute(
            "apply",
            session_id=session_id,
            request=review_result(2, applied["review_subject_digest"], action="close"),
        )
        engine.execute("close", session_id=session_id, expected_state_version=3, outcome="positive")

    def test_doctor_probes_a_terminal_session_without_finding_a_defect(self):
        for abandoned in (False, True):
            with self.subTest(abandoned=abandoned), project() as (_root, engine):
                session_id = "abandoned" if abandoned else "closed"
                self._closed_session(engine, session_id, abandoned=abandoned)

                doctor = engine.execute("doctor", session_id=session_id)

                self.assertEqual(doctor["findings"], [])
                self.assertEqual(doctor["status"], "ok")
                # The probes must not have advanced the session they inspected.
                self.assertEqual(
                    engine.repository.load(session_id)["state_version"],
                    doctor["state_version"],
                )

    def test_a_closed_session_is_not_regated_by_a_rule_it_predates(self):
        with project() as (_root, engine):
            self._closed_session(engine, "predates")
            state = engine.repository.load("predates")
            # A session closed before the readiness gate reached its current
            # shape: the gate would refuse this round today, but it already
            # transitioned, and no mutation can reconcile it now.
            state["progress"]["fixture"]["status"] = "active"

            doctor = engine._doctor(state, False)

            self.assertEqual(doctor["findings"], [])
            self.assertEqual(doctor["status"], "ok")
            # The same state while still active must remain blocked.
            state["status"] = "active"
            self.assertIn(
                "unreconciled_active_progress",
                [item["code"] for item in engine._doctor(state, False)["findings"]],
            )

    def test_doctor_reports_a_terminal_receipt_that_disagrees_with_its_state(self):
        with project() as (_root, engine):
            self._closed_session(engine, "damaged")
            state = engine.repository.load("damaged")
            state["last_mutation"]["receipt"]["state_version"] += 1

            doctor = engine._doctor(state, False)

            self.assertEqual(doctor["status"], "blocked")
            self.assertIn("terminal_receipt_incoherent", [item["code"] for item in doctor["findings"]])

    def test_doctor_reports_a_replay_mismatch_when_the_close_reason_no_longer_matches(self):
        with project() as (_root, engine):
            self._closed_session(engine, "rewritten", abandoned=True)
            state = engine.repository.load("rewritten")
            state["events"][-1]["summary"] = "a different reason than the one that closed this session"

            doctor = engine._doctor(state, False)

            self.assertEqual(doctor["status"], "blocked")
            self.assertIn("terminal_replay_mismatch", [item["code"] for item in doctor["findings"]])

    def test_doctor_reports_a_terminal_session_with_no_replayable_receipt(self):
        with project() as (_root, engine):
            self._closed_session(engine, "unreplayable")
            state = engine.repository.load("unreplayable")
            state["last_mutation"] = None

            doctor = engine._doctor(state, False)

            self.assertEqual(doctor["status"], "blocked")
            self.assertEqual(
                [item["code"] for item in doctor["findings"]],
                ["terminal_replay_unavailable"],
            )


if __name__ == "__main__":
    unittest.main()

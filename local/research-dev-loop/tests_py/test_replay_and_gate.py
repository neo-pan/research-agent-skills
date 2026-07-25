from __future__ import annotations

import json
import unittest
from pathlib import Path

from rdl import rendering
from rdl.engine import RdlEngine
from rdl.model import RdlError
from rdl.store import Repository

from rdl_test_support import START, project, review_result, routine_delta


class ReplayAndGateTests(unittest.TestCase):
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
            engine.execute("apply", session_id="stale", request={"expected_state_version": 1, "risk": "routine"})
            before = engine.repository.current_generation("stale")
            with self.assertRaisesRegex(RdlError, "stale"):
                engine.execute("next", session_id="stale", expected_state_version=1)
            self.assertEqual(engine.repository.current_generation("stale"), before)

    def test_close_lost_response_replay_finds_terminal_session(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="close-replay", request=START)
            applied = engine.execute(
                "apply", session_id="close-replay", request=routine_delta(transition="close", risk="material")
            )
            engine.execute(
                "apply",
                session_id="close-replay",
                request=review_result(2, applied["review_subject_digest"]),
            )
            first = engine.execute("close", session_id="close-replay", expected_state_version=3, outcome="positive")
            second = engine.execute("close", session_id="close-replay", expected_state_version=3, outcome="positive")
            self.assertEqual(second, first)

    def test_terminal_replay_and_mutation_truth_table_has_zero_writes(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="terminal-matrix", request=START)
            applied = engine.execute(
                "apply",
                session_id="terminal-matrix",
                request=routine_delta(transition="close", outcome="positive", risk="material"),
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
                ("apply", {"request": {"expected_state_version": 4, "risk": "routine"}}, "terminal_session"),
                ("next", {"expected_state_version": 4}, "terminal_session"),
                ("close", {"expected_state_version": 4, "outcome": "positive"}, "terminal_session"),
                ("apply", {"request": {"expected_state_version": 2, "risk": "routine"}}, "state_version_conflict"),
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
                "apply", session_id="upgrade", request=routine_delta(transition="next", risk="routine") | {"decision": routine_delta()["decision"] | {"kind": "pivot"}}
            )
            self.assertEqual(receipt["effective_risk"], "material")
            self.assertEqual(receipt["risk_upgrade_reasons"], ["decision:pivot"])
            self.assertEqual(receipt["transition_readiness"], "needs_review")

    def test_scientific_close_is_always_material(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="close-upgrade", request=START)
            delta = routine_delta(transition="close", outcome="inconclusive", risk="routine")
            receipt = engine.execute("apply", session_id="close-upgrade", request=delta)
            self.assertEqual(receipt["effective_risk"], "material")
            self.assertEqual(receipt["risk_upgrade_reasons"], ["scientific_close:inconclusive"])
            self.assertEqual(receipt["transition_readiness"], "needs_review")

    def test_binding_only_apply_does_not_change_subject_digest(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="digest", request=START)
            applied = engine.execute("apply", session_id="digest", request=routine_delta(risk="material"))
            pack = engine.execute("review", session_id="digest", action="next")
            engine.execute("apply", session_id="digest", request=review_result(2, pack["subject_digest"], action="next"))
            state = engine.repository.load("digest")
            self.assertEqual(
                rendering.subject_digest(state, "next", []),
                applied["review_subject_digest"],
            )

    def test_artifact_resolution_changes_binding_and_exact_replay_is_idempotent(self):
        with project() as (root, engine):
            engine.execute("start", session_id="resolution-binding", request=START)
            initial = routine_delta(transition="close", outcome="inconclusive", risk="material")
            initial["artifacts"]["report"]["stability"] = "live"
            first = engine.execute("apply", session_id="resolution-binding", request=initial)
            stale_digest = first["review_subject_digest"]
            (root / "artifacts" / "report.json").write_text('{"changed":true}\n', encoding="utf-8")
            resolution_request = {
                "expected_state_version": 2,
                "risk": "routine",
                "artifact_resolutions": {
                    "retire": {
                        "artifact_ref": "A000001",
                        "kind": "retired",
                        "reason": "The live report is historical after normal updates.",
                    }
                },
            }
            reconciled = engine.execute("apply", session_id="resolution-binding", request=resolution_request)
            self.assertNotEqual(reconciled["review_subject_digest"], stale_digest)
            self.assertEqual(
                engine.execute("apply", session_id="resolution-binding", request=resolution_request),
                reconciled,
            )
            state = engine.repository.load("resolution-binding")
            self.assertEqual(len([item for item in state["artifacts"] if "resolution" in item]), 1)

            with self.assertRaises(RdlError) as stale:
                engine.execute(
                    "apply",
                    session_id="resolution-binding",
                    request=review_result(3, stale_digest, action="close"),
                )
            self.assertEqual(stale.exception.code, "stale_review_result")
            pack = engine.execute("review", session_id="resolution-binding", action="close")
            bound = engine.execute(
                "apply",
                session_id="resolution-binding",
                request=review_result(3, pack["subject_digest"], action="close"),
            )
            self.assertEqual(bound["transition_readiness"], "ready")

    def test_pre_resolution_schema_v2_fixture_recovers_and_closes_without_migration(self):
        fixture_path = Path(__file__).with_name("fixtures") / "pre_resolution_schema_v2.json"
        legacy_state = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertNotIn("resolution", legacy_state["artifacts"][0])
        self.assertEqual(
            rendering.subject_digest(legacy_state, "close", []),
            legacy_state["last_mutation"]["receipt"]["review_subject_digest"],
        )
        with project() as (root, _engine):
            repository = Repository(root)
            repository.commit(
                "legacy-drift",
                legacy_state,
                rendering.render_views(legacy_state),
            )
            engine = RdlEngine(root, repository)
            (root / "artifacts" / "report.json").write_text('{"changed":true}\n', encoding="utf-8")
            self.assertIn(
                "artifact_drift",
                [item["code"] for item in engine.execute("doctor", session_id="legacy-drift")["findings"]],
            )
            reconciled = engine.execute(
                "apply",
                session_id="legacy-drift",
                request={
                    "expected_state_version": 2,
                    "risk": "material",
                    "artifact_resolutions": {
                        "retire": {
                            "artifact_ref": "A000001",
                            "kind": "retired",
                            "reason": "The mutable report is historical rather than current support.",
                        }
                    },
                },
            )
            self.assertEqual(reconciled["transition_readiness"], "needs_review")
            pack = engine.execute("review", session_id="legacy-drift", action="close")
            bound = engine.execute(
                "apply",
                session_id="legacy-drift",
                request=review_result(3, pack["subject_digest"], action="close", verdict="pass_with_notes"),
            )
            self.assertEqual(bound["transition_readiness"], "ready")
            closed = engine.execute(
                "close",
                session_id="legacy-drift",
                expected_state_version=4,
                outcome="inconclusive",
            )
            self.assertEqual(closed["transition_readiness"], "terminal")
            self.assertEqual(
                engine.execute(
                    "close",
                    session_id="legacy-drift",
                    expected_state_version=4,
                    outcome="inconclusive",
                ),
                closed,
            )
            with self.assertRaises(RdlError) as terminal:
                engine.execute(
                    "apply",
                    session_id="legacy-drift",
                    request={"expected_state_version": 5, "risk": "routine"},
                )
            self.assertEqual(terminal.exception.code, "terminal_session")

    def test_accepted_blocking_finding_blocks_transition(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="finding", request=START)
            applied = engine.execute("apply", session_id="finding", request=routine_delta(risk="material"))
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
            applied = engine.execute("apply", session_id="cycles", request=routine_delta(risk="material"))
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
        cases = (
            (
                "live-binding",
                "the source binding is decision-grade",
                "the bound source is live and still requires a drift check",
                "the receipt verifies binding metadata, not future source stability",
                "live",
            ),
            (
                "independent-reproduction",
                "the result was independently reproduced",
                "the cited check ran in the same process and establishes internal consistency only",
                "same-process consistency check",
                "snapshot",
            ),
            (
                "premature-memory",
                "session progress says the semantic gate passed",
                "no review binding exists yet; this pack is the pending review request",
                "deterministic checks do not establish semantic readiness",
                "snapshot",
            ),
            (
                "mechanics-negative",
                "mechanics_negative is propagated through the candidate receipt",
                "the downstream receipt omits the negative mechanics classification",
                "classification propagation check found the omission",
                "snapshot",
            ),
            (
                "verifier-overclaim",
                "the verifier proves end-to-end behavior",
                "the verifier checks receipt shape only and cannot observe end-to-end behavior",
                "schema-only verifier capability",
                "snapshot",
            ),
            (
                "oom-classification",
                "the CUDA OOM occurred before optimizer work was consumed",
                "the receipt records a consumed optimizer-stage CUDA OOM",
                "optimizer-stage consumption and OOM taxonomy check",
                "snapshot",
            ),
        )
        for name, claim, counterevidence, verifier_summary, stability in cases:
            with self.subTest(name=name), project() as (_root, engine):
                engine.execute("start", session_id=name, request=START)
                delta = routine_delta(risk="material")
                delta["artifacts"]["report"]["stability"] = stability
                delta["artifacts"]["report"]["verifier"]["summary"] = verifier_summary
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
                engine.execute("apply", session_id=name, request=delta)
                pack = engine.execute("review", session_id=name, action="next")

                self.assertNotIn("artifact_lifecycle_guidance", pack)

                evidence = pack["round"]["evidence"]
                self.assertEqual([item["claim"] for item in evidence], [claim, claim])
                self.assertEqual([item["bearing"] for item in evidence], ["supports", "contradicts"])
                self.assertEqual(evidence[1]["summary"], counterevidence)
                self.assertEqual(pack["round"]["decision"]["evidence_refs"], ["E000001", "E000002"])
                artifact = pack["artifacts"][0]
                self.assertEqual(
                    set(artifact),
                    {"id", "kind", "path", "description", "stability", "size_bytes", "sha256", "verifier"},
                )
                self.assertEqual(artifact["path"], "artifacts/report.json")
                self.assertEqual(
                    artifact["verifier"],
                    {"name": "fixture", "status": "passed", "summary": verifier_summary},
                )
                self.assertEqual(artifact["stability"], stability)
                self.assertEqual(pack["session"]["progress"]["fixture"]["summary"], claim)
                size = len(json.dumps(pack, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))
                self.assertLessEqual(size, rendering.REVIEW_HARD_BYTES)


if __name__ == "__main__":
    unittest.main()

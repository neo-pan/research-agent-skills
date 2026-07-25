from __future__ import annotations

import threading
import unittest
import os
import subprocess
import sys
import json
from pathlib import Path
from unittest.mock import patch

from rdl import rendering
from rdl.engine import RdlEngine
from rdl.model import RdlError
from rdl.store import Repository

from rdl_test_support import START, project, routine_delta


class StorageAndArtifactTests(unittest.TestCase):
    def test_generation_layout_and_relative_pointer(self):
        with project() as (root, engine):
            engine.execute("start", session_id="layout", request=START)
            pointer = root / ".rdl" / "sessions" / "layout"
            self.assertTrue(pointer.is_symlink())
            self.assertFalse(pointer.readlink().is_absolute())
            self.assertEqual(pointer.resolve().name, "1")

    def test_failure_before_pointer_replace_preserves_old_generation_and_cleans_future(self):
        with project() as (root, engine):
            engine.execute("start", session_id="fault", request=START)
            def fail(point):
                if point == "after_generation_rename":
                    raise RuntimeError("injected")
            broken = RdlEngine(root, Repository(root, fail))
            with self.assertRaisesRegex(RuntimeError, "injected"):
                broken.execute("apply", session_id="fault", request={"expected_state_version": 1, "risk": "routine"})
            self.assertEqual(engine.repository.load("fault")["state_version"], 1)
            engine.execute("apply", session_id="fault", request={"expected_state_version": 1, "risk": "routine"})
            self.assertEqual(engine.repository.load("fault")["state_version"], 2)
            self.assertFalse((root / ".rdl" / ".store" / "fault" / ".tmp-orphan").exists())

    def test_every_transaction_fault_point_has_old_or_new_visibility(self):
        points = (
            "after_layout_fsync",
            "after_session_store_fsync",
            "after_file_fsync",
            "after_temp_fsync",
            "after_generation_rename",
            "after_store_fsync",
            "after_pointer_create",
            "after_pointer_replace",
            "after_sessions_fsync",
        )
        for point in points:
            with self.subTest(point=point), project() as (root, engine):
                engine.execute("start", session_id="matrix", request=START)
                fired = False
                def fail(actual):
                    nonlocal fired
                    if actual == point and not fired:
                        fired = True
                        raise RuntimeError(point)
                broken = RdlEngine(root, Repository(root, fail))
                delta = {"expected_state_version": 1, "risk": "routine"}
                with self.assertRaisesRegex(RuntimeError, point):
                    broken.execute("apply", session_id="matrix", request=delta)
                visible = engine.repository.load("matrix")["state_version"]
                self.assertIn(visible, {1, 2})
                replay = engine.execute("apply", session_id="matrix", request=delta)
                self.assertEqual(replay["state_version"], 2)

    def test_subprocess_kill_preserves_old_or_committed_generation(self):
        script = """
import os
import sys
from pathlib import Path
from rdl import RdlEngine
from rdl.store import Repository

def kill(point):
    if point == sys.argv[2]:
        os._exit(91)

RdlEngine(Path(sys.argv[1]), Repository(Path(sys.argv[1]), kill)).execute(
    "apply", session_id="kill", request={"expected_state_version": 1, "risk": "routine"}
)
"""
        for point, expected_visible in (("after_generation_rename", 1), ("after_pointer_replace", 2)):
            with self.subTest(point=point), project() as (root, engine):
                engine.execute("start", session_id="kill", request=START)
                result = subprocess.run(
                    [sys.executable, "-c", script, str(root), point],
                    check=False,
                    env=os.environ.copy(),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 91, result.stderr)
                self.assertEqual(engine.repository.load("kill")["state_version"], expected_visible)
                replay = engine.execute(
                    "apply", session_id="kill", request={"expected_state_version": 1, "risk": "routine"}
                )
                self.assertEqual(replay["state_version"], 2)

    def test_failure_after_pointer_replace_is_replayable(self):
        with project() as (root, engine):
            engine.execute("start", session_id="commit", request=START)
            def fail(point):
                if point == "after_pointer_replace":
                    raise RuntimeError("lost response")
            broken = RdlEngine(root, Repository(root, fail))
            delta = {"expected_state_version": 1, "risk": "routine"}
            with self.assertRaisesRegex(RuntimeError, "lost response"):
                broken.execute("apply", session_id="commit", request=delta)
            replay = engine.execute("apply", session_id="commit", request=delta)
            self.assertEqual(replay["state_version"], 2)

    def test_live_artifact_drift_blocks_transition_and_is_read_once(self):
        with project() as (root, engine):
            engine.execute("start", session_id="live", request=START)
            delta = routine_delta()
            delta["artifacts"]["report"]["stability"] = "live"
            engine.execute("apply", session_id="live", request=delta)
            (root / "artifacts" / "report.json").write_text('{"passed":false}\n', encoding="utf-8")
            doctor = engine.execute("doctor", session_id="live", diagnostics=True)
            self.assertEqual(doctor["status"], "blocked")
            self.assertEqual(doctor["diagnostics"]["artifact_read_counts"], {"artifacts/report.json": 1})
            with self.assertRaisesRegex(RdlError, "not ready"):
                engine.execute("next", session_id="live", expected_state_version=2)

    def test_drifted_decision_artifact_can_be_retired_to_reach_fresh_review(self):
        with project() as (root, engine):
            engine.execute("start", session_id="retire-drift", request=START)
            delta = routine_delta(transition="close", outcome="negative", risk="material")
            delta["artifacts"]["report"]["stability"] = "live"
            applied = engine.execute("apply", session_id="retire-drift", request=delta)
            self.assertEqual(applied["transition_readiness"], "needs_review")
            registered_sha = engine.repository.load("retire-drift")["artifacts"][0]["sha256"]

            (root / "artifacts" / "report.json").write_text('{"passed":false}\n', encoding="utf-8")
            doctor = engine.execute("doctor", session_id="retire-drift")
            self.assertIn("artifact_drift", [item["code"] for item in doctor["findings"]])
            with self.assertRaisesRegex(RdlError, "does not require review"):
                engine.execute("review", session_id="retire-drift", action="close")

            reconciled = engine.execute(
                "apply",
                session_id="retire-drift",
                request={
                    "expected_state_version": 2,
                    "risk": "routine",
                    "artifact_resolutions": {
                        "retire-running-report": {
                            "artifact_ref": "A000001",
                            "kind": "retired",
                            "reason": "The live report continued changing and is historical only.",
                        }
                    },
                },
            )
            self.assertEqual(reconciled["effective_risk"], "material")
            self.assertEqual(reconciled["transition_readiness"], "needs_review")
            state = engine.repository.load("retire-drift")
            resolution = state["artifacts"][0]["resolution"]
            self.assertEqual(state["artifacts"][0]["sha256"], registered_sha)
            self.assertEqual(resolution["kind"], "retired")
            self.assertEqual(resolution["observed"]["status"], "drifted")
            self.assertEqual(resolution["recorded_version"], 3)
            pack = engine.execute("review", session_id="retire-drift", action="close")
            self.assertEqual(pack["artifacts"][0]["resolution"], resolution)
            self.assertEqual(pack["artifact_lifecycle_guidance"], rendering.ARTIFACT_LIFECYCLE_GUIDANCE)
            self.assertEqual(
                json.dumps(pack, ensure_ascii=False).count(rendering.ARTIFACT_LIFECYCLE_GUIDANCE),
                1,
            )

    def test_adding_snapshot_alone_does_not_hide_unresolved_live_drift(self):
        with project() as (root, engine):
            engine.execute("start", session_id="snapshot-only", request=START)
            initial = routine_delta(transition="close", outcome="negative", risk="material")
            initial["artifacts"]["report"]["stability"] = "live"
            engine.execute("apply", session_id="snapshot-only", request=initial)
            (root / "artifacts" / "report.json").write_text('{"changed":true}\n', encoding="utf-8")
            (root / "artifacts" / "final.json").write_text('{"changed":true}\n', encoding="utf-8")
            engine.execute(
                "apply",
                session_id="snapshot-only",
                request={
                    "expected_state_version": 2,
                    "risk": "routine",
                    "artifacts": {
                        "snapshot": {
                            "kind": "report",
                            "path": "artifacts/final.json",
                            "description": "frozen copy",
                            "stability": "snapshot",
                        }
                    },
                },
            )
            doctor = engine.execute("doctor", session_id="snapshot-only")
            self.assertIn("artifact_drift", [item["code"] for item in doctor["findings"]])
            with self.assertRaises(RdlError) as review:
                engine.execute("review", session_id="snapshot-only", action="close")
            self.assertEqual(review.exception.code, "review_not_required")

    def test_superseded_artifact_binds_same_apply_snapshot_into_closure(self):
        with project() as (root, engine):
            engine.execute("start", session_id="supersede", request=START)
            delta = routine_delta(transition="close", outcome="inconclusive", risk="material")
            delta["artifacts"]["report"]["stability"] = "live"
            engine.execute("apply", session_id="supersede", request=delta)
            (root / "artifacts" / "report.json").write_text('{"passed":false}\n', encoding="utf-8")
            (root / "artifacts" / "final.json").write_text('{"passed":false}\n', encoding="utf-8")

            receipt = engine.execute(
                "apply",
                session_id="supersede",
                request={
                    "expected_state_version": 2,
                    "risk": "material",
                    "artifacts": {
                        "final-snapshot": {
                            "kind": "report",
                            "path": "artifacts/final.json",
                            "description": "frozen final report",
                            "stability": "snapshot",
                        }
                    },
                    "artifact_resolutions": {
                        "freeze-report": {
                            "artifact_ref": "A000001",
                            "kind": "superseded",
                            "replacement_ref": "final-snapshot",
                            "reason": "The final snapshot replaces the running report.",
                        }
                    },
                },
            )
            self.assertEqual(receipt["transition_readiness"], "needs_review")
            state = engine.repository.load("supersede")
            self.assertEqual(
                state["artifacts"][0]["resolution"]["replacement_artifact_id"],
                "A000002",
            )
            pack = engine.execute("review", session_id="supersede", action="close")
            self.assertEqual({item["id"] for item in pack["artifacts"]}, {"A000001", "A000002"})

    def test_resolution_without_candidate_transition_is_rejected_without_writes(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="no-transition", request=START)
            engine.execute(
                "apply",
                session_id="no-transition",
                request={
                    "expected_state_version": 1,
                    "risk": "routine",
                    "artifacts": {
                        "live": {
                            "kind": "report",
                            "path": "artifacts/report.json",
                            "description": "running report",
                            "stability": "live",
                        }
                    },
                },
            )
            before = engine.repository.current_generation("no-transition")
            with self.assertRaisesRegex(RdlError, "candidate transition") as error:
                engine.execute(
                    "apply",
                    session_id="no-transition",
                    request={
                        "expected_state_version": 2,
                        "risk": "routine",
                        "evidence": {
                            "observation": {
                                "claim": "the running report was observed",
                                "summary": "bounded observation",
                                "bearing": "context",
                                "strength": "weak",
                                "artifact_refs": ["A000001"],
                                "uncertainty": "no transition decision",
                            }
                        },
                        "artifact_resolutions": {
                            "retire": {
                                "artifact_ref": "A000001",
                                "kind": "retired",
                                "reason": "No longer current.",
                            }
                        },
                    },
                )
            self.assertEqual(error.exception.code, "artifact_resolution_not_relevant")
            self.assertEqual(engine.repository.current_generation("no-transition"), before)
            self.assertEqual(engine.repository.load("no-transition")["state_version"], 2)

    def test_rejected_resolution_preserves_unreferenced_generations(self):
        with project() as (root, engine):
            engine.execute("start", session_id="reject-generations", request=START)
            initial = routine_delta(transition="close", outcome="inconclusive", risk="material")
            initial["artifacts"]["report"]["stability"] = "live"
            engine.execute("apply", session_id="reject-generations", request=initial)
            orphan = root / ".rdl" / ".store" / "reject-generations" / "99"
            orphan.mkdir()
            with self.assertRaises(RdlError) as error:
                engine.execute(
                    "apply",
                    session_id="reject-generations",
                    request={
                        "expected_state_version": 2,
                        "risk": "routine",
                        "artifact_resolutions": {
                            "duplicate": {
                                "artifact_ref": "A000001",
                                "kind": "retired",
                                "reason": "first declaration",
                            },
                            "duplicate-again": {
                                "artifact_ref": "A000001",
                                "kind": "retired",
                                "reason": "second declaration",
                            },
                        },
                    },
                )
            self.assertEqual(error.exception.code, "invalid_artifact_resolution")
            self.assertTrue(orphan.is_dir())

    def test_superseding_same_file_aliases_are_rejected_without_writes(self):
        cases = ("same-path", "dot-path", "symlink", "hard-link")
        for case in cases:
            with self.subTest(case=case), project() as (root, engine):
                engine.execute("start", session_id="identity", request=START)
                initial = routine_delta(transition="close", outcome="inconclusive", risk="material")
                initial["artifacts"]["report"]["stability"] = "live"
                engine.execute("apply", session_id="identity", request=initial)
                replacement_path = "artifacts/report.json"
                if case == "dot-path":
                    replacement_path = "artifacts/./report.json"
                elif case == "symlink":
                    (root / "artifacts" / "alias.json").symlink_to("report.json")
                    replacement_path = "artifacts/alias.json"
                elif case == "hard-link":
                    os.link(root / "artifacts" / "report.json", root / "artifacts" / "hard.json")
                    replacement_path = "artifacts/hard.json"
                before = engine.repository.current_generation("identity")
                with self.assertRaises(RdlError) as error:
                    engine.execute(
                        "apply",
                        session_id="identity",
                        request={
                            "expected_state_version": 2,
                            "risk": "material",
                            "artifacts": {
                                "replacement": {
                                    "kind": "report",
                                    "path": replacement_path,
                                    "description": "replacement candidate",
                                    "stability": "snapshot",
                                }
                            },
                            "artifact_resolutions": {
                                "supersede": {
                                    "artifact_ref": "A000001",
                                    "kind": "superseded",
                                    "replacement_ref": "replacement",
                                    "reason": "Bind a frozen replacement.",
                                }
                            },
                        },
                    )
                self.assertEqual(error.exception.code, "invalid_artifact_resolution")
                self.assertEqual(engine.repository.current_generation("identity"), before)
                self.assertEqual(engine.repository.load("identity")["state_version"], 2)

    def test_artifact_resolution_validation_matrix_is_atomic(self):
        cases = (
            ("unknown", "unknown_reference"),
            ("snapshot-target", "invalid_artifact_resolution"),
            ("duplicate-target", "invalid_artifact_resolution"),
            ("retired-extra-replacement", "invalid_artifact_resolution"),
            ("superseded-missing-replacement", "invalid_artifact_resolution"),
            ("durable-replacement", "invalid_artifact_resolution"),
            ("live-replacement", "invalid_artifact_resolution"),
            ("same-apply-target-id", "invalid_artifact_resolution"),
            ("unrelated-target", "artifact_resolution_not_relevant"),
            ("wrong-kind", "invalid_value"),
        )
        for case, expected_code in cases:
            with self.subTest(case=case), project() as (root, engine):
                (root / "artifacts" / "other.json").write_text('{"other":true}\n', encoding="utf-8")
                engine.execute("start", session_id="validation", request=START)
                initial = routine_delta(transition="close", outcome="inconclusive", risk="material")
                initial["artifacts"]["report"]["stability"] = (
                    "snapshot" if case == "snapshot-target" else "live"
                )
                if case in {"durable-replacement", "unrelated-target"}:
                    initial["artifacts"]["other"] = {
                        "kind": "report",
                        "path": "artifacts/other.json",
                        "description": "other artifact",
                        "stability": "snapshot" if case == "durable-replacement" else "live",
                    }
                engine.execute("apply", session_id="validation", request=initial)
                resolution = {
                    "artifact_ref": "A000001",
                    "kind": "retired",
                    "reason": "Historical only.",
                }
                request = {
                    "expected_state_version": 2,
                    "risk": "routine",
                    "artifact_resolutions": {"resolution": resolution},
                }
                if case == "unknown":
                    resolution["artifact_ref"] = "A999999"
                elif case == "duplicate-target":
                    request["artifact_resolutions"]["duplicate"] = dict(resolution)
                elif case == "retired-extra-replacement":
                    resolution["replacement_ref"] = "replacement"
                elif case == "superseded-missing-replacement":
                    resolution["kind"] = "superseded"
                elif case == "durable-replacement":
                    resolution.update({"kind": "superseded", "replacement_ref": "A000002"})
                elif case == "live-replacement":
                    resolution.update({"kind": "superseded", "replacement_ref": "replacement"})
                    request["artifacts"] = {
                        "replacement": {
                            "kind": "report",
                            "path": "artifacts/other.json",
                            "description": "still changing",
                            "stability": "live",
                        }
                    }
                elif case == "same-apply-target-id":
                    resolution["artifact_ref"] = "A000002"
                    request["artifacts"] = {
                        "new-target": {
                            "kind": "report",
                            "path": "artifacts/other.json",
                            "description": "new live target",
                            "stability": "live",
                        }
                    }
                    request["evidence"] = {
                        "new-target-evidence": {
                            "claim": "the new target was observed",
                            "summary": "same-apply evidence",
                            "bearing": "context",
                            "strength": "weak",
                            "artifact_refs": ["new-target"],
                            "uncertainty": "not yet durable before this apply",
                        }
                    }
                elif case == "unrelated-target":
                    resolution["artifact_ref"] = "A000002"
                elif case == "wrong-kind":
                    resolution["kind"] = "acknowledged"
                before = engine.repository.current_generation("validation")
                with self.assertRaises(RdlError) as error:
                    engine.execute("apply", session_id="validation", request=request)
                self.assertEqual(error.exception.code, expected_code)
                self.assertEqual(engine.repository.current_generation("validation"), before)
                self.assertEqual(engine.repository.load("validation")["state_version"], 2)

    def test_missing_or_unreadable_target_can_be_superseded_with_honest_observation(self):
        for observed_status in ("missing", "unreadable"):
            with self.subTest(observed_status=observed_status), project() as (root, engine):
                engine.execute("start", session_id="observation", request=START)
                initial = routine_delta(transition="close", outcome="inconclusive", risk="material")
                initial["artifacts"]["report"]["stability"] = "live"
                engine.execute("apply", session_id="observation", request=initial)
                target = (root / "artifacts" / "report.json").resolve()
                (root / "artifacts" / "final.json").write_text('{"final":true}\n', encoding="utf-8")
                if observed_status == "missing":
                    target.unlink()

                request = {
                    "expected_state_version": 2,
                    "risk": "material",
                    "artifacts": {
                        "replacement": {
                            "kind": "report",
                            "path": "artifacts/final.json",
                            "description": "frozen replacement",
                            "stability": "snapshot",
                        }
                    },
                    "artifact_resolutions": {
                        "supersede": {
                            "artifact_ref": "A000001",
                            "kind": "superseded",
                            "replacement_ref": "replacement",
                            "reason": "Replace the unavailable live source.",
                        }
                    },
                }
                if observed_status == "missing":
                    engine.execute("apply", session_id="observation", request=request)
                else:
                    original_open = type(target).open

                    def unreadable(path, *args, **kwargs):
                        mode = args[0] if args else kwargs.get("mode", "r")
                        if path.resolve() == target and "b" in mode:
                            raise PermissionError("fixture unreadable")
                        return original_open(path, *args, **kwargs)

                    with patch.object(type(target), "open", unreadable):
                        engine.execute("apply", session_id="observation", request=request)
                resolution = engine.repository.load("observation")["artifacts"][0]["resolution"]
                self.assertEqual(resolution["observed"], {"status": observed_status})

    def test_unverifiable_filesystem_identity_rejects_supersession_without_writes(self):
        with project() as (root, engine):
            engine.execute("start", session_id="identity-unknown", request=START)
            initial = routine_delta(transition="close", outcome="inconclusive", risk="material")
            initial["artifacts"]["report"]["stability"] = "live"
            engine.execute("apply", session_id="identity-unknown", request=initial)
            (root / "artifacts" / "final.json").write_text('{"final":true}\n', encoding="utf-8")
            target = (root / "artifacts" / "report.json").resolve()
            original_stat = type(target).stat

            def unverifiable(path, *args, **kwargs):
                if path == target:
                    raise PermissionError("fixture identity unavailable")
                return original_stat(path, *args, **kwargs)

            request = {
                "expected_state_version": 2,
                "risk": "material",
                "artifacts": {
                    "replacement": {
                        "kind": "report",
                        "path": "artifacts/final.json",
                        "description": "frozen replacement",
                        "stability": "snapshot",
                    }
                },
                "artifact_resolutions": {
                    "supersede": {
                        "artifact_ref": "A000001",
                        "kind": "superseded",
                        "replacement_ref": "replacement",
                        "reason": "Replace the live source.",
                    }
                },
            }
            before = engine.repository.current_generation("identity-unknown")
            with patch.object(type(target), "stat", unverifiable):
                with self.assertRaises(RdlError) as error:
                    engine.execute("apply", session_id="identity-unknown", request=request)
            self.assertEqual(error.exception.code, "artifact_identity_unverifiable")
            self.assertEqual(engine.repository.current_generation("identity-unknown"), before)

    def test_symlink_loop_is_typed_and_supersession_rejects_without_writes(self):
        with project() as (root, engine):
            engine.execute("start", session_id="identity-loop", request=START)
            initial = routine_delta(transition="close", outcome="inconclusive", risk="material")
            initial["artifacts"]["report"]["stability"] = "live"
            engine.execute("apply", session_id="identity-loop", request=initial)
            target = root / "artifacts" / "report.json"
            target.unlink()
            target.symlink_to("report.json")
            (root / "artifacts" / "final.json").write_text('{"final":true}\n', encoding="utf-8")

            doctor = engine.execute("doctor", session_id="identity-loop")
            self.assertIn("artifact_unreadable", [item["code"] for item in doctor["findings"]])
            before = engine.repository.current_generation("identity-loop")
            with self.assertRaises(RdlError) as error:
                engine.execute(
                    "apply",
                    session_id="identity-loop",
                    request={
                        "expected_state_version": 2,
                        "risk": "material",
                        "artifacts": {
                            "replacement": {
                                "kind": "report",
                                "path": "artifacts/final.json",
                                "description": "frozen replacement",
                                "stability": "snapshot",
                            }
                        },
                        "artifact_resolutions": {
                            "supersede": {
                                "artifact_ref": "A000001",
                                "kind": "superseded",
                                "replacement_ref": "replacement",
                                "reason": "Replace the unresolvable live path.",
                            }
                        },
                    },
                )
            self.assertEqual(error.exception.code, "artifact_identity_unverifiable")
            self.assertEqual(engine.repository.current_generation("identity-loop"), before)
            self.assertEqual(engine.repository.load("identity-loop")["state_version"], 2)

    def test_same_apply_decision_can_make_existing_artifact_relevant_for_resolution(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="candidate-relevance", request=START)
            engine.execute(
                "apply",
                session_id="candidate-relevance",
                request={
                    "expected_state_version": 1,
                    "risk": "routine",
                    "artifacts": {
                        "live": {
                            "kind": "report",
                            "path": "artifacts/report.json",
                            "description": "running report",
                            "stability": "live",
                        }
                    },
                },
            )
            receipt = engine.execute(
                "apply",
                session_id="candidate-relevance",
                request={
                    "expected_state_version": 2,
                    "risk": "routine",
                    "evidence": {
                        "result": {
                            "claim": "the historical run was observed",
                            "summary": "bounded historical observation",
                            "bearing": "context",
                            "strength": "weak",
                            "artifact_refs": ["A000001"],
                            "uncertainty": "the live file is not current evidence",
                        }
                    },
                    "decision": {
                        "kind": "narrow",
                        "subject": "retain only the bounded historical observation",
                        "evidence_refs": ["result"],
                        "uncertainty": "current bytes are not decision-grade",
                        "remaining_unknowns": ["current behavior"],
                        "next_step": "obtain fresh evidence in a later session",
                        "recommended_transition": "close",
                        "close_outcome": "inconclusive",
                    },
                    "artifact_resolutions": {
                        "retire": {
                            "artifact_ref": "A000001",
                            "kind": "retired",
                            "reason": "Keep the artifact as historical context only.",
                        }
                    },
                },
            )
            self.assertEqual(receipt["transition_readiness"], "needs_review")
            self.assertEqual(
                engine.repository.load("candidate-relevance")["artifacts"][0]["resolution"]["kind"],
                "retired",
            )
            observed = engine.repository.load("candidate-relevance")["artifacts"][0]["resolution"]["observed"]
            self.assertEqual(observed["status"], "unchanged")
            self.assertIn("size_bytes", observed)
            self.assertIn("sha256", observed)

    def test_apply_reads_each_artifact_path_once(self):
        with project() as (root, engine):
            engine.execute("start", session_id="reads", request=START)
            artifact = (root / "artifacts" / "report.json").resolve()
            original = type(artifact).open
            reads = 0
            def counted(path, *args, **kwargs):
                nonlocal reads
                mode = args[0] if args else kwargs.get("mode", "r")
                if path.resolve() == artifact and "b" in mode:
                    reads += 1
                return original(path, *args, **kwargs)
            delta = routine_delta()
            delta["artifacts"]["report"]["stability"] = "live"
            delta["artifacts"]["same-report"] = delta["artifacts"]["report"] | {"path": "artifacts/./report.json"}
            delta["evidence"]["result"]["artifact_refs"] = ["report", "same-report"]
            with patch.object(type(artifact), "open", counted):
                engine.execute("apply", session_id="reads", request=delta)
            self.assertEqual(reads, 1)

    def test_missing_live_artifact_is_read_once(self):
        with project() as (root, engine):
            engine.execute("start", session_id="missing", request=START)
            delta = routine_delta(risk="material")
            delta["artifacts"]["report"]["stability"] = "live"
            engine.execute("apply", session_id="missing", request=delta)
            (root / "artifacts" / "report.json").unlink()
            doctor = engine.execute("doctor", session_id="missing", diagnostics=True)
            self.assertEqual(doctor["diagnostics"]["artifact_read_counts"], {"artifacts/report.json": 1})
            self.assertIn("artifact_missing", [item["code"] for item in doctor["findings"]])
            with self.assertRaisesRegex(RdlError, "does not require review"):
                engine.execute("review", session_id="missing", action="next")

    def test_prior_round_cited_evidence_and_live_artifact_remain_in_subject_and_gate(self):
        with project() as (root, engine):
            engine.execute("start", session_id="closure", request=START)
            first = routine_delta()
            first["artifacts"]["report"]["stability"] = "live"
            engine.execute("apply", session_id="closure", request=first)
            engine.execute("next", session_id="closure", expected_state_version=2)
            second = routine_delta(version=3, risk="material")
            second["decision"]["evidence_refs"] = ["E000001", "result"]
            engine.execute("apply", session_id="closure", request=second)
            pack = engine.execute("review", session_id="closure", action="next")
            self.assertEqual({item["id"] for item in pack["round"]["evidence"]}, {"E000001", "E000002"})
            self.assertEqual({item["id"] for item in pack["artifacts"]}, {"A000001", "A000002"})
            (root / "artifacts" / "report.json").write_text('{"changed":true}\n', encoding="utf-8")
            doctor = engine.execute("doctor", session_id="closure")
            self.assertIn("artifact_drift", [item["code"] for item in doctor["findings"]])

    def test_prior_round_relevant_live_artifact_can_be_retired(self):
        with project() as (root, engine):
            engine.execute("start", session_id="prior-resolution", request=START)
            first = routine_delta()
            first["artifacts"]["report"]["stability"] = "live"
            engine.execute("apply", session_id="prior-resolution", request=first)
            engine.execute("next", session_id="prior-resolution", expected_state_version=2)
            second = routine_delta(version=3, transition="close", outcome="inconclusive", risk="material")
            second["decision"]["evidence_refs"] = ["E000001", "result"]
            engine.execute("apply", session_id="prior-resolution", request=second)
            (root / "artifacts" / "report.json").write_text('{"changed":true}\n', encoding="utf-8")
            reconciled = engine.execute(
                "apply",
                session_id="prior-resolution",
                request={
                    "expected_state_version": 4,
                    "risk": "routine",
                    "artifact_resolutions": {
                        "retire-prior": {
                            "artifact_ref": "A000001",
                            "kind": "retired",
                            "reason": "The prior-round live file is retained as historical context.",
                        }
                    },
                },
            )
            self.assertEqual(reconciled["transition_readiness"], "needs_review")
            pack = engine.execute("review", session_id="prior-resolution", action="close")
            self.assertEqual({item["id"] for item in pack["artifacts"]}, {"A000001", "A000002"})

    def test_directory_bootstrap_fsyncs_each_parent(self):
        with project() as (root, _engine):
            class TrackingRepository(Repository):
                def __init__(self, project_root):
                    super().__init__(project_root)
                    self.synced = []
                def _fsync_dir(self, path):
                    self.synced.append(Path(path).resolve())
                    super()._fsync_dir(path)
            repository = TrackingRepository(root)
            RdlEngine(root, repository).execute("start", session_id="durable", request=START)
            synced = set(repository.synced)
            self.assertTrue({root.resolve(), repository.rdl_root, repository.store_root}.issubset(synced))

    def test_successful_commit_keeps_only_current_and_previous_generation(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="retention", request=START)
            engine.execute("apply", session_id="retention", request={"expected_state_version": 1, "risk": "routine"})
            engine.execute("apply", session_id="retention", request={"expected_state_version": 2, "risk": "routine"})
            diagnostics = engine.execute("doctor", session_id="retention", diagnostics=True)["diagnostics"]["generations"]
            self.assertEqual(diagnostics, {"temporary": [], "unreferenced": []})

    def test_concurrent_different_apply_requests_have_one_winner(self):
        with project() as (root, engine):
            engine.execute("start", session_id="apply-race", request=START)
            outcomes = []
            guard = threading.Lock()
            def apply(summary):
                request = {
                    "expected_state_version": 1,
                    "risk": "routine",
                    "progress_updates": {
                        "race": {"status": "active", "summary": summary, "blocking": False}
                    },
                }
                try:
                    result = RdlEngine(root).execute("apply", session_id="apply-race", request=request)
                except RdlError as exc:
                    result = exc.result()
                with guard:
                    outcomes.append(result)
            threads = [threading.Thread(target=apply, args=(summary,)) for summary in ("one", "two")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(sum(item["status"] == "ok" for item in outcomes), 1)
            self.assertEqual(sum(item.get("code") == "state_version_conflict" for item in outcomes), 1)

    def test_two_concurrent_starts_create_at_most_one_active_session(self):
        with project() as (root, _engine):
            outcomes = []
            lock = threading.Lock()
            def start(name):
                try:
                    result = RdlEngine(root).execute("start", session_id=name, request=START)
                except RdlError as exc:
                    result = exc.result()
                with lock:
                    outcomes.append(result)
            threads = [threading.Thread(target=start, args=(name,)) for name in ("a", "b")]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(sum(item["status"] == "ok" for item in outcomes), 1)
            self.assertEqual(len(Repository(root).active_session_ids()), 1)

    def test_doctor_reports_view_drift_and_next_generation_repairs_it(self):
        with project() as (_root, engine):
            engine.execute("start", session_id="views", request=START)
            generation = engine.repository.current_generation("views")
            (generation / "progress.md").write_text("tampered\n", encoding="utf-8")
            codes = [item["code"] for item in engine.execute("doctor", session_id="views")["findings"]]
            self.assertIn("derived_view_drift", codes)
            engine.execute("apply", session_id="views", request={"expected_state_version": 1, "risk": "routine"})
            codes = [item["code"] for item in engine.execute("doctor", session_id="views")["findings"]]
            self.assertNotIn("derived_view_drift", codes)


if __name__ == "__main__":
    unittest.main()

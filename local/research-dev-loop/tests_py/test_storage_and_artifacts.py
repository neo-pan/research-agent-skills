from __future__ import annotations

import threading
import unittest
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

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

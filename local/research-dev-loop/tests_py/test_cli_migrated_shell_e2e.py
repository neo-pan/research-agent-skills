import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from rdl import integrity, store
from rdl.cli import main
from rdl.session import SessionStore

from rdl_test_support import (
    COMPLETE_BUILD_EVIDENCE,
    COMPLETE_INTENT,
    COMPLETE_INTERPRETATION,
    COMPLETE_RESEARCH_EVIDENCE,
    COMPLETE_WORK,
    complete_decision,
    complete_final_report,
    complete_review,
    refresh_integrity,
    write_json,
)


class MigratedShellE2ETests(unittest.TestCase):
    def test_research_flow_advances_then_closes_through_python_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mission.md").write_text("# Mission\n\nFull research flow.\n", encoding="utf-8")

            code, result = run_cli(root, ["start", "research", "mission.md", "--session-id", "flow", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")

            session_dir = root / ".rdl" / "sessions" / "flow"
            self.assert_session_shape(session_dir, mode="research")

            code, result = run_cli(root, ["review", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["next_action"], str(session_dir / "rounds" / "001" / "review.md"))

            round_one = session_dir / "rounds" / "001"
            (round_one / "review.md").write_text(complete_review("continue"), encoding="utf-8")
            code, result = run_cli(root, ["decide", "continue", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["next_action"], str(round_one / "decision.md"))
            (round_one / "decision.md").write_text(complete_decision_with_next_loop("continue", "claim", "build"), encoding="utf-8")
            (round_one / "evidence.md").write_text(COMPLETE_RESEARCH_EVIDENCE, encoding="utf-8")
            (round_one / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["next", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["round"], 2)
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())
            self.assertIn("recommended next loop build", (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8"))

            round_two = session_dir / "rounds" / "002"
            code, result = run_cli(root, ["review", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["next_action"], str(round_two / "review.md"))
            (round_two / "review.md").write_text(complete_review("close-positive"), encoding="utf-8")
            code, result = run_cli(root, ["decide", "close-positive", "--json"])
            self.assertEqual(code, 0)
            (round_two / "decision.md").write_text(complete_decision("close-positive", "claim"), encoding="utf-8")
            (round_two / "evidence.md").write_text(COMPLETE_RESEARCH_EVIDENCE, encoding="utf-8")
            (round_two / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
            write_artifact_file(root, "artifacts/check.log", "fixture close evidence\n")
            (session_dir / "artifact-manifest.json").write_text(artifact_manifest("E1"), encoding="utf-8")
            (session_dir / "final-report.md").write_text(complete_final_report("positive"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["close", "positive", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["next_action"], "closed-positive")
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "closed-positive")
            self.assertIn("## Session Closed", (session_dir / "decision-ledger.md").read_text(encoding="utf-8"))

    def test_build_flow_requires_verification_then_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plan.md").write_text("# Build Plan\n\nFull build flow.\n", encoding="utf-8")

            code, result = run_cli(root, ["start", "build", "plan.md", "--session-id", "build_flow", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["mode"], "build")
            session_dir = root / ".rdl" / "sessions" / "build_flow"
            self.assert_session_shape(session_dir, mode="build")

            round_one = session_dir / "rounds" / "001"
            (round_one / "review.md").write_text(complete_review("accept"), encoding="utf-8")
            (round_one / "decision.md").write_text(complete_decision("accept", "capability"), encoding="utf-8")
            (round_one / "intent.md").write_text(COMPLETE_INTENT, encoding="utf-8")
            (round_one / "work.md").write_text(COMPLETE_WORK, encoding="utf-8")
            (round_one / "evidence.md").write_text("# Evidence\n\nNo verification recorded.\n", encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["next", "--json"])
            self.assertEqual(code, 2)
            self.assertIn("missing_verification_evidence", blocker_codes(result))
            self.assertFalse((session_dir / "rounds" / "002").exists())

            (round_one / "evidence.md").write_text(COMPLETE_BUILD_EVIDENCE, encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())
            code, result = run_cli(root, ["next", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["round"], 2)
            self.assertIn("Mode: build", (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8"))

    def test_dogfood_long_session_recovery_after_mode_profile_memory_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mission.md").write_text("# Mission\n\nRecover a long mixed RDL session.\n", encoding="utf-8")

            code, result = run_cli(root, ["start", "research", "mission.md", "--session-id", "dogfood_recovery", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["mode"], "research")
            session_dir = root / ".rdl" / "sessions" / "dogfood_recovery"

            round_one = session_dir / "rounds" / "001"
            (round_one / "evidence.md").write_text(research_evidence("EV1"), encoding="utf-8")
            (round_one / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
            (round_one / "review.md").write_text(complete_review("continue"), encoding="utf-8")
            (round_one / "decision.md").write_text(
                dogfood_decision(
                    "continue",
                    "claim",
                    "build",
                    "parser normalization assumptions remain unresolved",
                    "build fixture parser capability",
                    "EV1",
                ),
                encoding="utf-8",
            )
            write_artifact_manifest(
                session_dir,
                (
                    artifact_record("EV1", 1, "research claim evidence"),
                ),
            )
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["next", "--mode", "build", "--profile", "build-update", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["mode"], "build")
            self.assertEqual(result["profile"], "build-update")
            prompt_two = (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Mode: build", prompt_two)
            self.assertIn("Profile: build-update", prompt_two)
            self.assertIn("parser normalization assumptions remain unresolved", prompt_two)
            self.assertIn("Next Smallest Step: build fixture parser capability", prompt_two)

            round_two = session_dir / "rounds" / "002"
            (round_two / "intent.md").write_text(COMPLETE_INTENT, encoding="utf-8")
            (round_two / "work.md").write_text(COMPLETE_WORK, encoding="utf-8")
            (round_two / "evidence.md").write_text(build_evidence("EV2"), encoding="utf-8")
            (round_two / "decision.md").write_text(
                dogfood_decision(
                    "accept",
                    "capability",
                    "research",
                    "sample coverage still needs review",
                    "inspect parser sample coverage",
                    "EV2",
                ),
                encoding="utf-8",
            )
            write_artifact_manifest(
                session_dir,
                (
                    artifact_record("EV1", 1, "research claim evidence"),
                    artifact_record("EV2", 2, "build verification evidence"),
                ),
            )
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["next", "--mode", "research", "--profile", "checkpoint", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["mode"], "research")
            self.assertEqual(result["profile"], "checkpoint")
            prompt_three = (session_dir / "rounds" / "003" / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Mode: research", prompt_three)
            self.assertIn("Profile: checkpoint", prompt_three)
            self.assertIn("sample coverage still needs review", prompt_three)
            self.assertIn("Next Smallest Step: inspect parser sample coverage", prompt_three)

            code, result = run_cli(root, ["memory", "--check", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["memory_status"], "needs_attention")
            self.assertEqual(result["details"]["progress_gaps"], ["Active", "Blocked", "Deferred"])
            self.assertIn("Dataset or Workload", result["details"]["factor_gaps"])
            self.assertEqual(result["details"]["deterministic_updates"]["Completed"], 2)

            code, result = run_cli(root, ["memory", "--write", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["memory_status"], "written")
            progress = (session_dir / "progress.md").read_text(encoding="utf-8")
            self.assertIn("| round-001 | continue | [artifact:EV1] | 001 |", progress)
            self.assertIn("| round-002 | accept | [artifact:EV2] | 002 |", progress)
            self.assertIn("## Session Summary Refresh", (session_dir / "decision-ledger.md").read_text(encoding="utf-8"))

            self.assertEqual(
                run_cli(
                    root,
                    [
                        "progress",
                        "active",
                        "--item",
                        "coverage",
                        "--mode",
                        "research",
                        "--text",
                        "parser sample coverage review",
                        "--blocking",
                        "no",
                        "--trigger",
                        "after build artifact audit",
                        "--json",
                    ],
                )[0],
                0,
            )
            self.assertEqual(run_cli(root, ["progress", "none", "--section", "Blocked", "--reason", "no current blockers", "--json"])[0], 0)
            self.assertEqual(run_cli(root, ["progress", "none", "--section", "Deferred", "--reason", "no deferred work", "--json"])[0], 0)
            progress_path = session_dir / "progress.md"
            progress_path.write_text(
                progress_path.read_text(encoding="utf-8").replace(
                    "| Question | Owner | Blocking? | Resolution |\n"
                    "|---|---|---|---|\n",
                    "| Question | Owner | Blocking? | Resolution |\n"
                    "|---|---|---|---|\n"
                    "| sample coverage still needs review | team | no | inspect parser sample coverage |\n",
                ),
                encoding="utf-8",
            )
            integrity.refresh(SessionStore(root).active_session())
            set_all_factors(root)

            code, result = run_cli(root, ["memory", "--check", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["memory_status"], "healthy")
            self.assertEqual(result["details"]["progress_gaps"], [])
            self.assertEqual(result["details"]["factor_gaps"], [])

            code, result = run_cli(root, ["handoff", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["handoff_status"], "ready")
            self.assertEqual(result["details"]["current_focus"], "- parser sample coverage review")
            self.assertEqual(result["details"]["last_decision"]["decision"], "none recorded")
            self.assertEqual(result["details"]["latest_completed_decision"]["round"], 2)
            self.assertEqual(result["details"]["latest_completed_decision"]["decision"], "accept")
            self.assertEqual(result["details"]["latest_completed_decision"]["closes"], "capability")
            self.assertIn("sample coverage still needs review", result["details"]["open_questions"])
            self.assertEqual(result["details"]["memory"]["memory_status"], "healthy")

    def test_descriptor_ignores_unknown_round_files_but_requires_protected_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mission.md").write_text("# Mission\n\nDescriptor fixture.\n", encoding="utf-8")
            code, _ = run_cli(root, ["start", "research", "mission.md", "--session-id", "descriptor", "--json"])
            self.assertEqual(code, 0)
            session_dir = root / ".rdl" / "sessions" / "descriptor"
            round_dir = session_dir / "rounds" / "001"
            (round_dir / "notes.md").write_text("not protocol state\n", encoding="utf-8")
            (round_dir / "nested").mkdir()
            (round_dir / "nested" / "prompt.md").write_text("# Nested\n", encoding="utf-8")

            code, result = run_cli(root, ["doctor", "--json"])
            self.assertEqual(code, 2)
            files = {blocker.get("file") for blocker in result["blockers"]}
            self.assertNotIn("rounds/001/notes.md", files)
            self.assertNotIn("rounds/001/nested/prompt.md", files)

            integrity_manifest = store.read_json(session_dir / "integrity.json")
            integrity_manifest["entries"] = [
                entry for entry in integrity_manifest["entries"] if entry.get("path") != "rounds/001/prompt.md"
            ]
            write_json(session_dir / "integrity.json", integrity_manifest)

            code, result = run_cli(root, ["doctor", "--json"])
            self.assertEqual(code, 1)
            self.assertIn("missing_integrity_entry", blocker_codes(result))

    def test_start_refuses_corrupt_existing_sessions_before_creating_new_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mission.md").write_text("# Mission\n\nStart guard fixture.\n", encoding="utf-8")
            broken = root / ".rdl" / "sessions" / "broken"
            broken.mkdir(parents=True)

            code, result = run_cli(root, ["start", "research", "mission.md", "--session-id", "new", "--json"])
            self.assertEqual(code, 1)
            self.assertIn("missing_state", blocker_codes(result))
            self.assertFalse((root / ".rdl" / "sessions" / "new").exists())

    def test_guard_stop_records_command_only_and_session_only_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = ready_continue_session(root, "guard_command_only")

            code, result = run_cli(root, ["guard-stop", "--guard-command-id", "cmd-1", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["round"], 2)
            state = store.read_json(session_dir / "state.json")
            self.assertIsNone(state["guard_session_id"])
            self.assertEqual(state["last_guard_command_id"], "cmd-1")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = ready_continue_session(root, "guard_session_only")

            code, result = run_cli(root, ["guard-stop", "--guard-session-id", "guard_session_only", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(result["round"], 2)
            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["guard_session_id"], "guard_session_only")
            self.assertIsNone(state["last_guard_command_id"])

    def test_close_blocks_template_report_and_missing_reusable_lessons_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "template_report")
            template = Path(__file__).resolve().parents[1] / "templates" / "final-report.md"
            (session_dir / "final-report.md").write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["close", "positive", "--json"])
            self.assertEqual(code, 2)
            codes = blocker_codes(result)
            self.assertIn("missing_final_report_section", codes)
            self.assertIn("incomplete_close_checklist", codes)
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = close_ready_session(root, "missing_lessons")
            report = session_dir / "final-report.md"
            text = report.read_text(encoding="utf-8")
            report.write_text(text.replace("\n## Reusable Lessons\n\nnone\n", "\n"), encoding="utf-8")
            integrity.refresh(SessionStore(root).active_session())

            code, result = run_cli(root, ["close", "positive", "--json"])
            self.assertEqual(code, 2)
            self.assertIn("missing_final_report_section", blocker_codes(result))
            self.assertEqual(store.read_json(session_dir / "state.json")["status"], "active")

    def assert_session_shape(self, session_dir: Path, mode: str) -> None:
        self.assertTrue((session_dir / "state.json").is_file())
        self.assertTrue((session_dir / "integrity.json").is_file())
        self.assertTrue((session_dir / "mission.md").is_file())
        self.assertTrue((session_dir / "factors.md").is_file())
        self.assertTrue((session_dir / "artifact-manifest.json").is_file())
        self.assertTrue((session_dir / "decision-ledger.md").is_file())
        self.assertTrue((session_dir / "progress.md").is_file())
        self.assertTrue((session_dir / "rounds" / "001" / "prompt.md").is_file())
        state = store.read_json(session_dir / "state.json")
        self.assertEqual(state["mode"], mode)
        self.assertIsNone(state["guard_session_id"])
        self.assertIsNone(state["last_guard_command_id"])
        entries = store.read_json(session_dir / "integrity.json")["entries"]
        policies = {entry["path"]: entry["policy"] for entry in entries}
        self.assertEqual(policies["state.json"], "cli_owned")
        self.assertEqual(policies["decision-ledger.md"], "append_only")
        self.assertEqual(policies["rounds/001/prompt.md"], "managed_prefix")
        self.assertEqual(policies["mission.md"], "human_owned")


def ready_continue_session(root: Path, session_id: str) -> Path:
    (root / "mission.md").write_text("# Mission\n\nGuard fixture.\n", encoding="utf-8")
    code, _ = run_cli(root, ["start", "research", "mission.md", "--session-id", session_id, "--json"])
    assert code == 0
    session_dir = root / ".rdl" / "sessions" / session_id
    round_dir = session_dir / "rounds" / "001"
    (round_dir / "review.md").write_text(complete_review("continue"), encoding="utf-8")
    (round_dir / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
    (round_dir / "evidence.md").write_text(COMPLETE_RESEARCH_EVIDENCE, encoding="utf-8")
    (round_dir / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
    integrity.refresh(SessionStore(root).active_session())
    return session_dir


def close_ready_session(root: Path, session_id: str) -> Path:
    session_dir = ready_continue_session(root, session_id)
    round_dir = session_dir / "rounds" / "001"
    (round_dir / "review.md").write_text(complete_review("close-positive"), encoding="utf-8")
    (round_dir / "decision.md").write_text(complete_decision("close-positive", "claim"), encoding="utf-8")
    write_artifact_file(root, "artifacts/check.log", "fixture close evidence\n")
    (session_dir / "artifact-manifest.json").write_text(artifact_manifest("E1"), encoding="utf-8")
    (session_dir / "final-report.md").write_text(complete_final_report("positive"), encoding="utf-8")
    integrity.refresh(SessionStore(root).active_session())
    return session_dir


def artifact_manifest(artifact_id: str) -> str:
    return json.dumps(
        {
            "artifacts": [
                {
                    "id": artifact_id,
                    "kind": "log",
                    "path": "artifacts/check.log",
                    "round": 1,
                    "description": "Fixture evidence artifact",
                }
            ]
        },
        indent=2,
    ) + "\n"


def artifact_record(artifact_id: str, round_number: int, description: str) -> dict:
    return {
        "id": artifact_id,
        "kind": "log",
        "path": f"artifacts/{artifact_id.lower()}.log",
        "round": round_number,
        "description": description,
    }


def write_artifact_manifest(session_dir: Path, records: tuple[dict, ...]) -> None:
    root = session_dir.parents[2]
    for record in records:
        path = record.get("path")
        if isinstance(path, str) and path:
            write_artifact_file(root, path, f"{record.get('id', 'artifact')} evidence\n")
    (session_dir / "artifact-manifest.json").write_text(json.dumps({"artifacts": list(records)}, indent=2) + "\n", encoding="utf-8")


def write_artifact_file(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def research_evidence(artifact_id: str) -> str:
    return f"""# Evidence

Research evidence: fixture claim evidence.

## Evaluation Integrity

Manual fixture integrity reviewed.

## Missing Evidence

parser normalization assumptions remain unresolved

## Evidence Budget

One local fixture check.

## Evidence Artifacts

| ID | Kind | Path or URL | Supports | Notes |
|---|---|---|---|---|
| {artifact_id} | log | artifacts/{artifact_id.lower()}.log | claim | fixture |
"""


def build_evidence(artifact_id: str) -> str:
    return f"""# Evidence

Verification evidence: fixture capability check passed.

## Evaluation Integrity

Manual fixture integrity reviewed.

## Missing Evidence

sample coverage still needs review

## Evidence Budget

One local fixture check.

## Evidence Artifacts

| ID | Kind | Path or URL | Supports | Notes |
|---|---|---|---|---|
| {artifact_id} | log | artifacts/{artifact_id.lower()}.log | capability | fixture |
"""


def dogfood_decision(decision: str, closes: str, next_loop: str, unknown: str, next_step: str, artifact_id: str) -> str:
    return f"""# Decision

Decision: {decision}
Closes: {closes}
Evidence: [artifact:{artifact_id}]
Uncertainty: bounded
What this rules out: unsupported alternatives
What remains unknown: {unknown}
Direction changed: no
Prior directions checked: fixture prior directions checked
Stall response: no staleness signal
Recommended next loop: {next_loop}
Next smallest step: {next_step}
"""


def set_all_factors(root: Path) -> None:
    for section in (
        "Model or Algorithm",
        "Dataset or Workload",
        "Seed and Sampling",
        "Hardware or Backend",
        "Prompt or Policy Version",
        "Baseline",
        "Candidate-Visible Context",
        "Metric Definition",
        "Evaluator or Validator Version",
        "Environment",
        "Known Non-Determinism",
    ):
        code, result = run_cli(root, ["factors", "set", "--section", section, "--value", f"dogfood {section}", "--json"])
        if code != 0:
            raise AssertionError(result)


def complete_decision_with_next_loop(decision: str, closes: str, next_loop: str) -> str:
    return complete_decision(decision, closes).replace(
        "Recommended next loop: none",
        f"Recommended next loop: {next_loop}",
    )


def blocker_codes(result: dict) -> set[str]:
    return {blocker["code"] for blocker in result.get("blockers", [])}


def run_cli(root: Path, argv: list[str]) -> tuple[int, dict]:
    stdout = StringIO()
    with change_dir(root), redirect_stdout(stdout), redirect_stderr(StringIO()):
        code = main(argv)
    return code, json.loads(stdout.getvalue())


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


if __name__ == "__main__":
    unittest.main()

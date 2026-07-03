import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from rdl import integrity
from rdl.cli import main

from rdl_test_support import create_session


class CliSessionMemoryEditTests(unittest.TestCase):
    def test_progress_active_appends_row_and_clears_active_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "progress_active")

            code, result = run_cli_json(
                root,
                [
                    "progress",
                    "active",
                    "--item",
                    "parser",
                    "--mode",
                    "build",
                    "--text",
                    "raw parser capability",
                    "--blocking",
                    "no",
                    "--trigger",
                    "sample coverage review",
                    "--json",
                ],
            )

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["updated_file"], "progress.md")
            self.assertEqual(result["details"]["updated_section"], "Active")
            self.assertTrue(result["details"]["row_added"])
            progress = (session_dir / "progress.md").read_text(encoding="utf-8")
            self.assertIn("| parser | build | raw parser capability | no | sample coverage review |", progress)
            memory_code, memory_result = run_cli_json(root, ["memory", "--check", "--json"])
            self.assertEqual(memory_code, 0)
            self.assertNotIn("Active", memory_result["details"]["progress_gaps"])
            self.assertEqual(_integrity_sha(session_dir, "progress.md"), integrity.file_sha256(session_dir / "progress.md"))

    def test_progress_blocked_deferred_and_none_append_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "progress_rows")

            self.assertEqual(
                run_cli_json(
                    root,
                    [
                        "progress",
                        "blocked",
                        "--item",
                        "normalizer",
                        "--reason",
                        "schema mismatch",
                        "--needed",
                        "inspect raw headers",
                        "--impact",
                        "blocks parser confidence",
                        "--json",
                    ],
                )[0],
                0,
            )
            self.assertEqual(
                run_cli_json(
                    root,
                    [
                        "progress",
                        "deferred",
                        "--item",
                        "benchmark",
                        "--reason",
                        "needs normalized data",
                        "--trigger",
                        "after parser pass",
                        "--json",
                    ],
                )[0],
                0,
            )
            self.assertEqual(
                run_cli_json(root, ["progress", "none", "--section", "Active", "--reason", "no current active item", "--json"])[0],
                0,
            )

            progress = (session_dir / "progress.md").read_text(encoding="utf-8")
            self.assertIn("| normalizer | schema mismatch | inspect raw headers | blocks parser confidence |", progress)
            self.assertIn("| benchmark | needs normalized data | after parser pass |", progress)
            self.assertIn("| no-active-items | research | none: no current active item | no | - |", progress)

    def test_factors_set_and_note_update_factor_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "factors_edit")

            code, result = run_cli_json(
                root,
                ["factors", "set", "--section", "Dataset or Workload", "--value", "fixture QA workload", "--json"],
            )
            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["write_mode"], "set")
            code, result = run_cli_json(
                root,
                ["factors", "note", "--section", "Dataset or Workload", "--value", "sampled first 100 rows", "--json"],
            )
            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["write_mode"], "note")

            factors = (session_dir / "factors.md").read_text(encoding="utf-8")
            self.assertIn("## Dataset or Workload\n\nfixture QA workload\n- sampled first 100 rows\n", factors)
            memory_code, memory_result = run_cli_json(root, ["memory", "--check", "--json"])
            self.assertEqual(memory_code, 0)
            self.assertNotIn("Dataset or Workload", memory_result["details"]["factor_gaps"])
            self.assertEqual(_integrity_sha(session_dir, "factors.md"), integrity.file_sha256(session_dir / "factors.md"))

    def test_progress_rejects_invalid_arguments_without_partial_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "progress_invalid")
            before = (session_dir / "progress.md").read_text(encoding="utf-8")

            code, result = run_cli_json(
                root,
                [
                    "progress",
                    "active",
                    "--item",
                    "parser",
                    "--mode",
                    "deploy",
                    "--text",
                    "parser",
                    "--blocking",
                    "maybe",
                    "--trigger",
                    "review",
                    "--json",
                ],
            )

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertIn("invalid_mode", {blocker["code"] for blocker in result["blockers"]})
            self.assertIn("invalid_blocking_value", {blocker["code"] for blocker in result["blockers"]})
            self.assertEqual((session_dir / "progress.md").read_text(encoding="utf-8"), before)

    def test_factors_rejects_invalid_section_without_partial_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "factor_invalid")
            before = (session_dir / "factors.md").read_text(encoding="utf-8")

            code, result = run_cli_json(root, ["factors", "set", "--section", "Dataset", "--value", "fixture", "--json"])

            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["blockers"][0]["code"], "invalid_factor_section")
            self.assertEqual((session_dir / "factors.md").read_text(encoding="utf-8"), before)

    def test_progress_blocks_for_noncanonical_progress_table_without_partial_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "progress_bad_table")
            progress_path = session_dir / "progress.md"
            progress_path.write_text(
                progress_path.read_text(encoding="utf-8").replace(
                    "| Item | Mode | Claim or Capability | Blocking? | Next Review Trigger |",
                    "| Item | Mode | Claim | Blocking? | Next Review Trigger |",
                ),
                encoding="utf-8",
            )
            before = progress_path.read_text(encoding="utf-8")

            code, result = run_cli_json(
                root,
                [
                    "progress",
                    "active",
                    "--item",
                    "parser",
                    "--mode",
                    "build",
                    "--text",
                    "parser",
                    "--blocking",
                    "no",
                    "--trigger",
                    "review",
                    "--json",
                ],
            )

            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blockers"][0]["code"], "unsupported_progress_table")
            self.assertEqual(progress_path.read_text(encoding="utf-8"), before)

    def test_progress_and_factors_block_without_active_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            progress_code, progress_result = run_cli_json(
                root,
                [
                    "progress",
                    "deferred",
                    "--item",
                    "bench",
                    "--reason",
                    "later",
                    "--trigger",
                    "after data",
                    "--json",
                ],
            )
            factors_code, factors_result = run_cli_json(
                root,
                ["factors", "set", "--section", "Dataset or Workload", "--value", "fixture", "--json"],
            )

            self.assertEqual(progress_code, 2)
            self.assertEqual(progress_result["blockers"][0]["code"], "no_active_session")
            self.assertEqual(factors_code, 2)
            self.assertEqual(factors_result["blockers"][0]["code"], "no_active_session")


def _integrity_sha(session_dir: Path, relative_path: str) -> str:
    manifest = json.loads((session_dir / "integrity.json").read_text(encoding="utf-8"))
    return next(entry["sha256"] for entry in manifest["entries"] if entry["path"] == relative_path)


def run_cli_json(root: Path, argv: list[str]) -> tuple[int, dict]:
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

import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from rdl import store
from rdl.cli import main

from rdl_test_support import complete_final_report, complete_research_round, create_session


class CliLockTests(unittest.TestCase):
    def test_mutating_commands_block_when_session_lock_exists(self):
        cases = (
            ("repair", ["repair", "--json"], lambda session: store.read_json(session / "state.json")["status"] == "active"),
            ("review", ["review", "--json"], lambda session: not (session / "rounds" / "001" / "review.md").exists()),
            ("decide", ["decide", "continue", "--json"], lambda session: not (session / "rounds" / "001" / "decision.md").exists()),
            ("next", ["next", "--json"], lambda session: not (session / "rounds" / "002").exists()),
            ("close", ["close", "positive", "--json"], lambda session: store.read_json(session / "state.json")["status"] == "active"),
            ("abandon", ["abandon", "operator", "stopped", "--json"], lambda session: store.read_json(session / "state.json")["status"] == "active"),
            ("guard-stop", ["guard-stop", "--json"], lambda session: not (session / "rounds" / "002").exists()),
        )

        for session_id, argv, unchanged in cases:
            with self.subTest(command=argv[0]):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    session_dir = create_session(root, session_id)
                    if argv[0] in {"next", "close", "guard-stop"}:
                        complete_research_round(session_dir, "close-positive" if argv[0] == "close" else "continue")
                    if argv[0] == "close":
                        (session_dir / "final-report.md").write_text(complete_final_report("positive"), encoding="utf-8")
                    _write_live_lock(session_dir)

                    code, result = run_cli(root, argv)

                    self.assertEqual(code, 2)
                    self.assertEqual(result["status"], "blocked")
                    self.assertEqual(result["action"], argv[0])
                    self.assertEqual(result["blockers"][0]["code"], "session_locked")
                    self.assertEqual(result["next_action"], "retry after lock clears")
                    self.assertTrue(unchanged(session_dir))
                    self.assertTrue((session_dir / ".lock").is_file())

    def test_successful_mutating_command_releases_session_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "lock_release")

            code, result = run_cli(root, ["abandon", "operator", "stopped", "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["action"], "abandon")
            self.assertFalse((session_dir / ".lock").exists())


def _write_live_lock(session_dir: Path) -> None:
    (session_dir / ".lock").write_text(f"pid={os.getpid()}\naction=test\ncreated_at_utc=2026-06-29T00:00:00Z\n", encoding="utf-8")


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
        self.previous = Path.cwd()
        os.chdir(self.path)

    def __exit__(self, exc_type, exc, tb):
        os.chdir(self.previous)


if __name__ == "__main__":
    unittest.main()

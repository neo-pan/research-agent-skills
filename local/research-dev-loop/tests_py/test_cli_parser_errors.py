import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from rdl.cli import main


class CliParserErrorTests(unittest.TestCase):
    def test_unknown_option_with_json_returns_structured_error(self):
        code, result = run_cli(["status", "--unknown", "--json"])

        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["action"], "status")
        self.assertEqual(result["blockers"][0]["code"], "unknown_option")
        self.assertEqual(result["next_action"], "Run rdl --help.")

    def test_missing_guard_session_id_with_json_returns_structured_error(self):
        code, result = run_cli(["guard-stop", "--guard-session-id", "--json"])

        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["action"], "guard-stop")
        self.assertEqual(result["blockers"][0]["code"], "missing_guard_session_id")
        self.assertEqual(result["next_action"], "Pass --guard-session-id <id>.")

    def test_missing_start_session_id_with_json_returns_structured_error(self):
        code, result = run_cli(["start", "research", "mission.md", "--session-id", "--json"])

        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["action"], "start")
        self.assertEqual(result["blockers"][0]["code"], "missing_session_id")
        self.assertEqual(result["next_action"], "Pass --session-id <id>.")

    def test_missing_profile_with_json_returns_structured_error(self):
        code, result = run_cli(["next", "--profile", "--json"])

        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["action"], "next")
        self.assertEqual(result["blockers"][0]["code"], "missing_profile")
        self.assertEqual(result["next_action"], "Pass --profile full-review, checkpoint, or build-update.")

    def test_unknown_command_with_json_returns_structured_error(self):
        code, result = run_cli(["unknown-command", "--json"])

        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["action"], "unknown-command")
        self.assertEqual(result["blockers"][0]["code"], "unknown_command")

    def test_main_none_uses_real_argv_for_json_parser_errors(self):
        stdout = StringIO()
        with patch.object(sys, "argv", ["rdl", "unknown-command", "--json"]):
            with redirect_stdout(stdout), redirect_stderr(StringIO()):
                code = main(None)
        result = json.loads(stdout.getvalue())

        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["action"], "unknown-command")
        self.assertEqual(result["blockers"][0]["code"], "unknown_command")


def run_cli(argv: list[str]) -> tuple[int, dict]:
    stdout = StringIO()
    with redirect_stdout(stdout), redirect_stderr(StringIO()):
        code = main(argv)
    return code, json.loads(stdout.getvalue())


if __name__ == "__main__":
    unittest.main()

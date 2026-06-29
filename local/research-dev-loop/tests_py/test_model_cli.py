import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from rdl.cli import main
from rdl.model import CloseOutcome, DecisionType, SessionMode, SessionPhase, SessionStatus


class ModelCliTests(unittest.TestCase):
    def test_enum_values_match_protocol_vocabulary(self):
        self.assertEqual([mode.value for mode in SessionMode], ["research", "build"])
        self.assertIn("interpret", {phase.value for phase in SessionPhase})
        self.assertIn("closed-inconclusive", {status.value for status in SessionStatus})
        self.assertIn("close-positive", {decision.value for decision in DecisionType})
        self.assertEqual([outcome.value for outcome in CloseOutcome], ["positive", "negative", "inconclusive"])

    def test_unsupported_enum_values_are_rejected(self):
        with self.assertRaises(ValueError):
            SessionMode("deploy")
        with self.assertRaises(ValueError):
            DecisionType("close-unknown")

    def test_cli_help_exits_successfully(self):
        with redirect_stdout(StringIO()):
            self.assertEqual(main(["--help"]), 0)

    def test_python_cli_does_not_claim_full_command_behavior(self):
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main(["next"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

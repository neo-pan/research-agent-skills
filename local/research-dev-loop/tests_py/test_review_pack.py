import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rdl import review_pack
from rdl.session import SessionStore

from rdl_test_support import complete_decision, complete_research_round, complete_review, create_session, set_current_round


class ReviewPackTests(unittest.TestCase):
    def test_builds_clean_rdl_context_pack_without_conversation_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack")
            complete_research_round(session_dir)
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(
                details={
                    "findings": [
                        {"category": "memory", "code": "session_memory_needs_attention"},
                        {"category": "semantic", "code": "semantic_review_recorded"},
                    ]
                }
            )

            pack = review_pack.build(session, "doctor", deterministic_report)

            record_paths = {record["path"] for record in pack.records}
            self.assertIn("progress.md", record_paths)
            self.assertIn("rounds/001/review.md", record_paths)
            self.assertEqual([finding["code"] for finding in pack.deterministic_findings], ["session_memory_needs_attention"])
            rendered = pack.as_dict()
            self.assertNotIn("conversation", rendered)
            self.assertNotIn("conversation_history", rendered)
            self.assertIn("text", rendered["records"][0])
            self.assertIn("reviewer_task", rendered)
            self.assertIn("finding_schema", rendered)
            self.assertIn("agent_review_signals", rendered)

    def test_repeated_next_step_is_agent_review_signal_not_deterministic_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_signal", profile="checkpoint")
            complete_research_round(session_dir)
            round_two = set_current_round(session_dir, 2)
            (round_two / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(details={"findings": []})

            pack = review_pack.build(session, "review", deterministic_report)

            self.assertIn("unchanged_next_smallest_step_across_rounds", {signal["code"] for signal in pack.agent_review_signals})
            self.assertEqual(pack.deterministic_findings, ())

    def test_includes_bounded_prior_completed_round_key_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "review_pack_history")
            complete_research_round(session_dir)
            _complete_prior_round(session_dir, 2)
            _complete_prior_round(session_dir, 3)
            set_current_round(session_dir, 4)
            session = SessionStore(root).active_session()
            deterministic_report = SimpleNamespace(details={"findings": []})

            pack = review_pack.build(session, "review", deterministic_report)

            record_paths = [record["path"] for record in pack.records]
            self.assertIn("rounds/004/prompt.md", record_paths)
            for round_number in (2, 3):
                for file_name in ("evidence.md", "interpretation.md", "review.md", "decision.md", "events.md"):
                    self.assertIn(f"rounds/{round_number:03d}/{file_name}", record_paths)
                self.assertNotIn(f"rounds/{round_number:03d}/prompt.md", record_paths)
                self.assertNotIn(f"rounds/{round_number:03d}/intent.md", record_paths)
                self.assertNotIn(f"rounds/{round_number:03d}/work.md", record_paths)
            self.assertNotIn("rounds/001/evidence.md", record_paths)


def _complete_prior_round(session_dir: Path, round_number: int) -> None:
    round_dir = set_current_round(session_dir, round_number)
    (round_dir / "evidence.md").write_text(f"# Evidence\n\nResearch evidence from round {round_number}.\n", encoding="utf-8")
    (round_dir / "interpretation.md").write_text(f"# Interpretation\n\nInterpretation from round {round_number}.\n", encoding="utf-8")
    (round_dir / "review.md").write_text(complete_review("continue"), encoding="utf-8")
    (round_dir / "decision.md").write_text(complete_decision("continue", "claim"), encoding="utf-8")
    (round_dir / "events.md").write_text(f"# Events\n\n## Operational Events\n\nRound {round_number} event.\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

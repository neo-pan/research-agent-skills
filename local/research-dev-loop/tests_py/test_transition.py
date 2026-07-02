import tempfile
import unittest
from pathlib import Path

from rdl import store, transition
from rdl.model import SessionPhase, SessionStatus
from rdl.session import SessionStore

from rdl_test_support import (
    complete_final_report,
    complete_research_round,
    create_session,
)


class TransitionTests(unittest.TestCase):
    def test_advance_updates_state_creates_prompt_and_appends_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "transition_next")
            complete_research_round(session_dir, "continue")
            session = SessionStore(root).active_session()

            result = transition.advance(session)

            state = store.read_json(session_dir / "state.json")
            self.assertEqual(result.phase, "plan")
            self.assertEqual(result.round, 2)
            self.assertEqual(result.next_action, str(session_dir / "rounds" / "002" / "prompt.md"))
            self.assertEqual(state["round"], 2)
            self.assertEqual(state["phase"], "plan")
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())
            prompt = (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Objective: Continue research session transition_next", prompt)
            self.assertIn("Previous Decision: continue; closes claim; recommended next loop none", prompt)
            ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
            self.assertIn("## Round 1 Decision", ledger)
            self.assertIn("- Next round: 002", ledger)

    def test_advance_carries_session_memory_into_next_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "carry")
            complete_research_round(session_dir, "continue")
            (session_dir / "progress.md").write_text(
                """# Progress

## Active

| Item | Mode | Claim or Capability | Blocking? | Next Review Trigger |
|---|---|---|---|---|
| parser | research | raw schema can normalize | yes | schema sample |

## Completed

| Item | Decision | Evidence | Round |
|---|---|---|---|

## Blocked

| Item | Reason | Needed Evidence or Input | Decision Impact |
|---|---|---|---|

## Deferred

| Item | Reason | Revisit Trigger |
|---|---|---|

## Open Questions

| Question | Owner | Blocking? | Resolution |
|---|---|---|---|
| explain count mismatch | agent | yes | - |

## Directions Tried

| Direction | Rounds | Outcome | Why Not Repeat |
|---|---|---|---|
| naive parse | 001 | rejected | missed schema variants |

## Staleness Watch

| Signal | Evidence | Response |
|---|---|---|
| repeated failure | EV1 | pivot parser |
""",
                encoding="utf-8",
            )
            decision_path = session_dir / "rounds" / "001" / "decision.md"
            decision_path.write_text(
                decision_path.read_text(encoding="utf-8")
                .replace("What remains unknown: later work", "What remains unknown: schema edge cases")
                .replace("Next smallest step: continue same mode", "Next smallest step: inspect sample schema"),
                encoding="utf-8",
            )
            session = SessionStore(root).active_session()

            transition.advance(session)

            prompt = (session_dir / "rounds" / "002" / "prompt.md").read_text(encoding="utf-8")
            self.assertIn("Claim or Capability Under Review:\n- raw schema can normalize", prompt)
            self.assertIn("- explain count mismatch", prompt)
            self.assertIn("- schema edge cases", prompt)
            self.assertIn("- naive parse", prompt)
            self.assertIn("- repeated failure", prompt)
            self.assertIn("Next Smallest Step: inspect sample schema", prompt)

    def test_advance_rejects_invalid_next_mode_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")
            session = SessionStore(root).active_session()

            with self.assertRaises(transition.TransitionBlocked) as raised:
                transition.advance(session, "deploy")

            self.assertEqual(raised.exception.blocker.code, "invalid_mode")
            self.assertFalse((session_dir / "rounds" / "002").exists())
            self.assertEqual(store.read_json(session_dir / "state.json")["mode"], "research")

    def test_advance_refuses_existing_next_round(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")
            (session_dir / "rounds" / "002").mkdir()
            session = SessionStore(root).active_session()

            with self.assertRaises(transition.TransitionBlocked) as raised:
                transition.advance(session)

            self.assertEqual(raised.exception.blocker.code, "next_round_exists")
            self.assertEqual(store.read_json(session_dir / "state.json")["round"], 1)

    def test_close_updates_state_and_appends_close_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "close-positive")
            (session_dir / "final-report.md").write_text(complete_final_report("positive"), encoding="utf-8")
            session = SessionStore(root).active_session()

            result = transition.close(session, "positive")

            state = store.read_json(session_dir / "state.json")
            self.assertEqual(result.phase, "complete")
            self.assertEqual(result.round, 1)
            self.assertEqual(result.next_action, "closed-positive")
            self.assertEqual(state["status"], "closed-positive")
            self.assertEqual(state["phase"], "complete")
            ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
            self.assertIn("## Session Closed", ledger)
            self.assertIn("- Outcome: positive", ledger)

    def test_abandon_updates_state_and_appends_ledger_and_progress_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            session = SessionStore(root).active_session()

            result = transition.abandon(session, "operator stopped duplicate effort")

            state = store.read_json(session_dir / "state.json")
            self.assertEqual(result.phase, "complete")
            self.assertEqual(result.next_action, "abandoned")
            self.assertEqual(state["status"], "abandoned")
            self.assertEqual(state["phase"], "complete")
            ledger = (session_dir / "decision-ledger.md").read_text(encoding="utf-8")
            progress = (session_dir / "progress.md").read_text(encoding="utf-8")
            self.assertIn("## Session Abandoned", ledger)
            self.assertIn("Scientific outcome claimed: none", ledger)
            self.assertIn("## Abandon Record", progress)
            self.assertIn("operator stopped duplicate effort", progress)

    def test_from_decision_closes_for_close_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "close-negative")
            session = SessionStore(root).active_session()

            result = transition.from_decision(session)

            self.assertEqual(result.phase, "complete")
            self.assertEqual(result.next_action, "closed-negative")
            self.assertFalse((session_dir / "rounds" / "002").exists())

    def test_from_decision_advances_for_non_close_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            complete_research_round(session_dir, "continue")
            session = SessionStore(root).active_session()

            result = transition.from_decision(session)

            self.assertEqual(result.phase, "plan")
            self.assertEqual(result.round, 2)
            self.assertTrue((session_dir / "rounds" / "002" / "prompt.md").is_file())

    def test_mark_guard_seen_updates_metadata_with_structured_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            session = SessionStore(root).active_session()

            transition.mark_guard_seen(session, "guard-session", "cmd-1")

            state = store.read_json(session_dir / "state.json")
            self.assertEqual(state["guard_session_id"], "guard-session")
            self.assertEqual(state["last_guard_command_id"], "cmd-1")

    def test_transition_updates_load_as_session_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            session = SessionStore(root).active_session()

            transition.abandon(session, "done")
            loaded = SessionStore(root)._load_session(session_dir)

            self.assertEqual(loaded.state.phase, SessionPhase.COMPLETE)
            self.assertEqual(loaded.state.status, SessionStatus.ABANDONED)


if __name__ == "__main__":
    unittest.main()

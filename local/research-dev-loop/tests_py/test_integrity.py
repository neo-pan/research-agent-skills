import hashlib
import tempfile
import unittest
from pathlib import Path

from rdl import integrity, store
from rdl.protocol import descriptor
from rdl.session import SessionStore

from rdl_test_support import create_session, refresh_integrity, set_current_round, write_json


class IntegrityTests(unittest.TestCase):
    def test_refresh_writes_policy_specific_manifest_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            session = SessionStore(root).active_session()

            (session_dir / "decision-ledger.md").write_text("# Decision Ledger\n\nAppended record.\n", encoding="utf-8")
            integrity.refresh(session)

            manifest = store.read_json(session_dir / "integrity.json")
            entries = {entry["path"]: entry for entry in manifest["entries"]}
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["session_id"], session.state.session_id)

            self.assertEqual(entries["state.json"]["policy"], "cli_owned")
            self.assertEqual(entries["decision-ledger.md"]["policy"], "append_only")
            self.assertEqual(entries["decision-ledger.md"]["size"], len((session_dir / "decision-ledger.md").read_bytes()))
            self.assertEqual(entries["decision-ledger.md"]["prefix_sha256"], entries["decision-ledger.md"]["sha256"])
            self.assertEqual(entries["rounds/001/prompt.md"]["policy"], "managed_prefix")
            self.assertIn("managed_sha256", entries["rounds/001/prompt.md"])
            self.assertEqual(entries["mission.md"]["policy"], "human_owned")

    def test_refresh_manifest_passes_session_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            session = SessionStore(root).active_session()

            integrity.refresh(session)

            self.assertEqual(SessionStore(root).active_session().audit().errors, ())
            self.assertTrue((session_dir / "integrity.json").is_file())

    def test_expected_policies_include_state_required_managed_prompt_when_missing_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            set_current_round(session_dir, 2)
            (session_dir / "rounds" / "002" / "prompt.md").unlink()
            refresh_integrity(session_dir)

            session = SessionStore(root).active_session()

            self.assertEqual(integrity.expected_policies(session)["rounds/002/prompt.md"], "managed_prefix")
            self.assertNotIn("rounds/002/prompt.md", integrity.existing_protocol_files(session))

    def test_audit_reports_missing_state_required_managed_prompt_entry_even_if_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            set_current_round(session_dir, 2)
            (session_dir / "rounds" / "002" / "prompt.md").unlink()
            refresh_integrity(session_dir)
            manifest = store.read_json(session_dir / "integrity.json")
            manifest["entries"] = [entry for entry in manifest["entries"] if entry["path"] != "rounds/002/prompt.md"]
            write_json(session_dir / "integrity.json", manifest)

            audit = SessionStore(root).active_session().audit()

            self.assertIn("missing_integrity_entry", {blocker.code for blocker in audit.errors})
            self.assertIn("missing_prompt", {blocker.code for blocker in audit.blockers})

    def test_managed_block_matches_bash_newline_semantics(self):
        text = "<!-- rdl:managed policy=managed_prefix -->\n# Prompt\n<!-- /rdl:managed -->\n\n## Notes\n"

        block = integrity.managed_block(text)

        self.assertEqual(
            hashlib.sha256(block.encode("utf-8")).hexdigest(),
            hashlib.sha256("<!-- rdl:managed policy=managed_prefix -->\n# Prompt\n<!-- /rdl:managed -->\n".encode("utf-8")).hexdigest(),
        )

    def test_refresh_uses_descriptor_policies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_session(root)
            session = SessionStore(root).active_session()

            integrity.refresh(session)

            manifest = store.read_json(session.root / "integrity.json")
            for entry in manifest["entries"]:
                with self.subTest(path=entry["path"]):
                    self.assertEqual(entry["policy"], descriptor.policy_for_path(entry["path"]))

    def test_refresh_ignores_files_under_invalid_round_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root)
            invalid_round = session_dir / "rounds" / "abc"
            invalid_round.mkdir()
            (invalid_round / "prompt.md").write_text("# Not a protocol prompt\n", encoding="utf-8")
            session = SessionStore(root).active_session()

            integrity.refresh(session)

            manifest = store.read_json(session.root / "integrity.json")
            self.assertNotIn("rounds/abc/prompt.md", {entry["path"] for entry in manifest["entries"]})
            self.assertEqual(SessionStore(root).active_session().audit().errors, ())


if __name__ == "__main__":
    unittest.main()

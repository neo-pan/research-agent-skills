import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from rdl import integrity, store
from rdl.cli import main

from rdl_test_support import complete_review, create_session, refresh_integrity


class CliRecordTests(unittest.TestCase):
    def test_record_artifact_adds_manifest_entry_and_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "record_artifact")
            artifact_path = root / "artifacts" / "run.log"
            artifact_path.parent.mkdir()
            artifact_path.write_text("fixture output\n", encoding="utf-8")

            code, result = run_cli(
                root,
                ["record", "artifact", "EV1", "log", "artifacts/run.log", "parser smoke output", "--json"],
            )

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["record_kind"], "artifact")
            self.assertEqual(result["details"]["record_id"], "EV1")
            manifest = store.read_json(session_dir / "artifact-manifest.json")
            self.assertEqual(len(manifest["artifacts"]), 1)
            artifact = manifest["artifacts"][0]
            self.assertEqual(artifact["id"], "EV1")
            self.assertEqual(artifact["kind"], "log")
            self.assertEqual(artifact["round"], 1)
            self.assertEqual(artifact["path"], "artifacts/run.log")
            self.assertEqual(artifact["size"], artifact_path.stat().st_size)
            self.assertEqual(artifact["sha256"], integrity.file_sha256(artifact_path))
            entries = {entry["path"] for entry in store.read_json(session_dir / "integrity.json")["entries"]}
            self.assertIn("artifact-manifest.json", entries)

    def test_record_artifact_blocks_duplicate_without_partial_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "record_duplicate")
            artifact_dir = root / "artifacts"
            artifact_dir.mkdir()
            (artifact_dir / "one.log").write_text("first\n", encoding="utf-8")
            (artifact_dir / "two.log").write_text("second\n", encoding="utf-8")
            self.assertEqual(
                run_cli(root, ["record", "artifact", "EV1", "log", "artifacts/one.log", "first", "--json"])[0],
                0,
            )
            before = (session_dir / "artifact-manifest.json").read_text(encoding="utf-8")

            code, result = run_cli(root, ["record", "artifact", "EV1", "log", "artifacts/two.log", "second", "--json"])

            self.assertEqual(code, 2)
            self.assertEqual(result["blockers"][0]["code"], "duplicate_artifact_id")
            self.assertEqual((session_dir / "artifact-manifest.json").read_text(encoding="utf-8"), before)

    def test_record_artifact_blocks_missing_local_path_without_partial_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "record_missing_artifact")
            before = (session_dir / "artifact-manifest.json").read_text(encoding="utf-8")

            code, result = run_cli(
                root,
                ["record", "artifact", "EV1", "log", "artifacts/missing.log", "missing output", "--json"],
            )

            self.assertEqual(code, 2)
            self.assertEqual(result["blockers"][0]["code"], "missing_artifact_path")
            self.assertEqual((session_dir / "artifact-manifest.json").read_text(encoding="utf-8"), before)

    def test_record_artifact_accepts_remote_url_without_local_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "record_remote_artifact")

            code, result = run_cli(
                root,
                ["record", "artifact", "EVURL", "log", "https://example.invalid/run.log", "remote output", "--json"],
            )

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["record_id"], "EVURL")
            artifact = store.read_json(session_dir / "artifact-manifest.json")["artifacts"][0]
            self.assertEqual(artifact["url"], "https://example.invalid/run.log")
            self.assertNotIn("path", artifact)
            self.assertNotIn("size", artifact)
            self.assertNotIn("sha256", artifact)

    def test_record_finding_writes_review_finding_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "record_finding")
            review_path = session_dir / "rounds" / "001" / "review.md"
            review_path.write_text(complete_review("continue"), encoding="utf-8")
            refresh_integrity(session_dir)

            code, result = run_cli(
                root,
                [
                    "record",
                    "finding",
                    "warning",
                    "evidence",
                    "rounds/001/evidence.md",
                    "coverage is thin",
                    "add fixture evidence",
                    "--json",
                ],
            )

            self.assertEqual(code, 0)
            self.assertEqual(result["details"]["record_kind"], "finding")
            review = review_path.read_text(encoding="utf-8")
            self.assertIn("- warning | evidence | rounds/001/evidence.md | coverage is thin | add fixture evidence", review)
            self.assertNotIn("\nnone\n\n## Accepted Corrections", review)
            manifest = store.read_json(session_dir / "integrity.json")
            entry = next(entry for entry in manifest["entries"] if entry["path"] == "rounds/001/review.md")
            self.assertEqual(entry["sha256"], integrity.file_sha256(review_path))

    def test_record_finding_rejects_invalid_category_without_partial_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "record_bad_finding")
            review_path = session_dir / "rounds" / "001" / "review.md"
            review_path.write_text(complete_review("continue"), encoding="utf-8")
            refresh_integrity(session_dir)
            before = review_path.read_text(encoding="utf-8")

            code, result = run_cli(
                root,
                ["record", "finding", "warning", "format", "review.md", "claim", "fix", "--json"],
            )

            self.assertEqual(code, 1)
            self.assertEqual(result["blockers"][0]["code"], "invalid_review_finding_category")
            self.assertEqual(review_path.read_text(encoding="utf-8"), before)

    def test_record_finding_blocks_for_malformed_existing_finding_without_partial_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session_dir = create_session(root, "record_malformed_finding")
            review_path = session_dir / "rounds" / "001" / "review.md"
            review_path.write_text(
                complete_review("continue").replace("none\n\n## Accepted Corrections", "malformed finding\n\n## Accepted Corrections"),
                encoding="utf-8",
            )
            refresh_integrity(session_dir)
            before = review_path.read_text(encoding="utf-8")

            code, result = run_cli(
                root,
                ["record", "finding", "warning", "evidence", "review.md", "claim", "fix", "--json"],
            )

            self.assertEqual(code, 1)
            self.assertEqual(result["blockers"][0]["code"], "invalid_review_finding")
            self.assertEqual(review_path.read_text(encoding="utf-8"), before)

    def test_record_blocks_without_active_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, result = run_cli(
                Path(tmp),
                ["record", "artifact", "EV1", "log", "artifacts/run.log", "parser smoke output", "--json"],
            )

            self.assertEqual(code, 2)
            self.assertEqual(result["blockers"][0]["code"], "no_active_session")


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

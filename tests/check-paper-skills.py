#!/usr/bin/env python3
"""Small offline checks for the migrated paper-delivery skills."""

from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SYNC_PATH = ROOT / "local/overleaf-project-sync/scripts/overleaf_sync.py"
spec = importlib.util.spec_from_file_location("overleaf_sync", SYNC_PATH)
assert spec and spec.loader
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class PaperSkillTests(unittest.TestCase):
    def test_manifested_skills_have_contract_files(self) -> None:
        for name in (
            "latex-compiling",
            "overleaf-project-sync",
            "latex-template-migration",
            "paper-submission-audit",
            "conference-rebuttal",
            "paper-story-design",
        ):
            skill = ROOT / "local" / name
            self.assertTrue((skill / "SKILL.md").is_file())
            self.assertTrue((skill / "agents/openai.yaml").is_file())

    def test_migrated_references_are_linked_and_present(self) -> None:
        expected = (
            "conference-rebuttal/references/response-structure.md",
            "conference-rebuttal/references/evidence-consistency-checklist.md",
            "paper-story-design/references/story-evidence-matrix.md",
            "paper-story-design/references/section-logic-checklist.md",
            "paper-story-design/references/drafting-templates.md",
            "latex-template-migration/references/submission-requirements-template.md",
            "paper-submission-audit/references/page-risk-audit-template.md",
            "overleaf-project-sync/references/operational-details.md",
        )
        for relative in expected:
            self.assertTrue((ROOT / "local" / relative).is_file(), relative)

    def test_sensitive_skills_are_explicit(self) -> None:
        for name in (
            "overleaf-project-sync",
            "latex-template-migration",
            "paper-submission-audit",
            "conference-rebuttal",
            "paper-story-design",
        ):
            config = (ROOT / "local" / name / "agents/openai.yaml").read_text(encoding="utf-8")
            self.assertIn("allow_implicit_invocation: false", config)

    def test_compare_files_reports_all_three_difference_classes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            remote = root / "remote"
            local = root / "local"
            remote.mkdir()
            local.mkdir()
            (remote / "same.tex").write_text("same")
            (local / "same.tex").write_text("same")
            (remote / "changed.tex").write_text("remote")
            (local / "changed.tex").write_text("local")
            (remote / "missing.tex").write_text("remote-only")
            (local / "extra.tex").write_text("local-only")
            changed, missing, extra, _ = sync.compare_files(remote, local, ())
            self.assertEqual(changed, ["changed.tex"])
            self.assertEqual(missing, ["missing.tex"])
            self.assertEqual(extra, ["extra.tex"])

    def run_sync(self, archive: Path, target: Path, *options: str) -> int:
        def download_fixture(url, cookie, output, timeout):
            shutil.copyfile(archive, output)

        argv = [
            str(SYNC_PATH), *options, "--target", str(target),
            "--url", "https://www.overleaf.com/project/test/download/zip",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(sync, "read_cookie", return_value="offline-fixture"),
            patch.object(sync, "download_zip", side_effect=download_fixture),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return sync.main()

    def test_update_preflights_all_ancestors_before_any_copy(self) -> None:
        for remote_path in ("z/main.tex", "z/sub/main.tex"):
            with self.subTest(remote_path=remote_path), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                target = root / "target"
                target.mkdir()
                (target / "a.tex").write_text("local original")
                (target / "z").write_text("local file")
                archive = root / "project.zip"
                with zipfile.ZipFile(archive, "w") as handle:
                    handle.writestr("a.tex", "remote replacement")
                    handle.writestr(remote_path, "remote source")
                with self.assertRaisesRegex(SystemExit, "non-directory parent"):
                    self.run_sync(archive, target, "update", "--overwrite")
                self.assertEqual((target / "a.tex").read_text(), "local original")
                self.assertEqual((target / "z").read_text(), "local file")
                self.assertEqual(sorted(p.name for p in target.iterdir()), ["a.tex", "z"])

    def test_update_preserves_paths_unless_wrapper_stripping_is_requested(self) -> None:
        for options, expected in (((), "latex/main.tex"), (("--strip-single-root",), "main.tex")):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                target = root / "target"
                target.mkdir()
                (target / "notes.txt").write_text("local only")
                archive = root / "project.zip"
                with zipfile.ZipFile(archive, "w") as handle:
                    handle.writestr("latex/main.tex", "remote source")
                self.assertEqual(self.run_sync(archive, target, "update", "--overwrite", *options), 0)
                self.assertEqual((target / expected).read_text(), "remote source")
                self.assertEqual((target / "notes.txt").read_text(), "local only")
                files = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
                self.assertEqual(files, sorted([expected, "notes.txt"]))

    def test_explicit_wrapper_stripping_rejects_unwrapped_zip_before_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            target.mkdir()
            (target / "main.tex").write_text("local original")
            archive = root / "project.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("main.tex", "remote replacement")
            with self.assertRaisesRegex(SystemExit, "single ZIP wrapper directory"):
                self.run_sync(archive, target, "update", "--overwrite", "--strip-single-root")
            self.assertEqual((target / "main.tex").read_text(), "local original")

    def test_check_and_dry_runs_leave_local_files_unchanged(self) -> None:
        for options, expected_status in (
            ((), 2),
            (("update",), 0),
            (("update", "--overwrite", "--dry-run"), 0),
        ):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                target = root / "target"
                target.mkdir()
                (target / "main.tex").write_text("local original")
                archive = root / "project.zip"
                with zipfile.ZipFile(archive, "w") as handle:
                    handle.writestr("main.tex", "remote replacement")
                    handle.writestr("sections/new.tex", "new source")
                self.assertEqual(self.run_sync(archive, target, *options), expected_status)
                self.assertEqual((target / "main.tex").read_text(), "local original")
                self.assertEqual(list(target.iterdir()), [target / "main.tex"])

    def test_safe_extract_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../../escape.txt", "bad")
            with self.assertRaises(SystemExit):
                sync.safe_extract(archive, root / "extract")

    def test_safe_extract_accepts_normal_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "good.zip"
            extract = root / "extract"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("project/main.tex", "\\documentclass{article}")
            extract.mkdir()
            sync.safe_extract(archive, extract)
            self.assertTrue((extract / "project/main.tex").is_file())

    def test_safe_destination_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            victim = root / "victim"
            target.mkdir()
            victim.write_text("original")
            (target / "paper.tex").symlink_to(victim)
            with self.assertRaises(SystemExit):
                sync.safe_destination(target, "paper.tex")

    def test_redirect_handler_rejects_cross_origin(self) -> None:
        request = sync.urllib.request.Request("https://www.overleaf.com/project/1/download/zip")
        handler = sync.SameOriginRedirectHandler()
        redirected = handler.redirect_request(
            request,
            object(),
            302,
            "Found",
            {},
            "https://www.overleaf.com/project/1/download/zip?version=2",
        )
        self.assertEqual(redirected.full_url, "https://www.overleaf.com/project/1/download/zip?version=2")
        with self.assertRaises(sync.urllib.error.HTTPError):
            handler.redirect_request(
                request, None, 302, "Found", {}, "https://evil.example/steal"
            )
        with self.assertRaisesRegex(sync.urllib.error.HTTPError, "invalid redirect URL"):
            handler.redirect_request(
                request, None, 302, "Found", {}, "https://www.overleaf.com:bad/zip"
            )
        with self.assertRaisesRegex(sync.urllib.error.HTTPError, "invalid redirect URL"):
            handler.redirect_request(request, None, 302, "Found", {}, "https://[bad/zip")
        with self.assertRaisesRegex(sync.urllib.error.HTTPError, "cross-origin redirect refused"):
            handler.redirect_request(
                request, None, 302, "Found", {}, "https://www.overleaf.com:0/zip"
            )

    def test_require_url_restricts_cookie_destination(self) -> None:
        with self.assertRaises(SystemExit):
            sync.require_url(sync.argparse.Namespace(url="http://evil.example/zip"))
        with self.assertRaises(SystemExit):
            sync.require_url(sync.argparse.Namespace(url="https://www.overleaf.com.evil.example/zip"))
        self.assertEqual(
            sync.require_url(
                sync.argparse.Namespace(url="https://www.overleaf.com/project/1/download/zip")
            ),
            "https://www.overleaf.com/project/1/download/zip",
        )
        self.assertEqual(
            sync.require_url(
                sync.argparse.Namespace(url="https://overleaf.com/project/1/download/zip")
            ),
            "https://www.overleaf.com/project/1/download/zip",
        )
        with self.assertRaises(SystemExit):
            sync.require_url(sync.argparse.Namespace(url="https://overleaf.com:bad/zip"))


if __name__ == "__main__":
    unittest.main()

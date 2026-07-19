from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests_py.rdl_test_support import START


SKILL_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = SKILL_ROOT / "bin" / "rdl"


class LauncherTests(unittest.TestCase):
    def run_launcher(
        self,
        launcher: Path,
        cwd: Path,
        *argv: str,
        stdin: dict | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        process_env = os.environ.copy()
        process_env.pop("PYTHONPATH", None)
        if env:
            process_env.update(env)
        return subprocess.run(
            [str(launcher), *argv],
            cwd=cwd,
            env=process_env,
            input=json.dumps(stdin) if stdin is not None else None,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_launcher_starts_from_unrelated_working_directory_without_pythonpath(self):
        with TemporaryDirectory(prefix="rdl launcher ") as tmp:
            project = Path(tmp) / "project with spaces"
            project.mkdir()
            result = self.run_launcher(LAUNCHER, project, "start", "--input", "-", stdin=START)

            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "ok")
            self.assertTrue((project / ".rdl").is_dir())
            self.assertFalse((SKILL_ROOT / ".rdl").exists())

    def test_launcher_follows_multiple_symlinks_and_prefers_bundled_package(self):
        with TemporaryDirectory(prefix="rdl links ") as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            first = root / "first rdl"
            second = root / "second rdl"
            first.symlink_to(LAUNCHER)
            second.symlink_to(first)
            hostile = root / "hostile"
            (hostile / "rdl").mkdir(parents=True)
            (hostile / "rdl" / "__init__.py").write_text("raise RuntimeError('wrong rdl')\n", encoding="utf-8")

            result = self.run_launcher(second, project, "handoff", env={"PYTHONPATH": str(hostile)})

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(result.stdout)["code"], "no_active_session")
            self.assertEqual(result.stderr, "")

    def test_launcher_preserves_cli_exit_codes_and_help_exception(self):
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            invalid = self.run_launcher(LAUNCHER, project)
            blocked = self.run_launcher(LAUNCHER, project, "handoff")
            help_result = self.run_launcher(LAUNCHER, project, "--help")

            self.assertEqual(invalid.returncode, 1)
            self.assertEqual(json.loads(invalid.stdout)["code"], "parser_error")
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(json.loads(blocked.stdout)["code"], "no_active_session")
            self.assertEqual(help_result.returncode, 0)
            self.assertIn("usage:", help_result.stdout)

    def test_launcher_and_module_entry_are_equivalent(self):
        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            launcher = self.run_launcher(LAUNCHER, project, "handoff")
            env = os.environ.copy()
            env["PYTHONPATH"] = str(SKILL_ROOT)
            module = subprocess.run(
                [sys.executable, "-m", "rdl", "handoff"],
                cwd=project,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual((launcher.returncode, launcher.stdout, launcher.stderr), (module.returncode, module.stdout, module.stderr))

    def test_launcher_does_not_write_bytecode_into_skill(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "skill copy"
            shutil.copytree(SKILL_ROOT, source)
            for cache in source.rglob("__pycache__"):
                shutil.rmtree(cache)
            launcher = source / "bin" / "rdl"
            result = self.run_launcher(launcher, Path(tmp), "handoff")

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(list(source.rglob("*.pyc")), [])
            self.assertEqual(list(source.rglob("__pycache__")), [])


if __name__ == "__main__":
    unittest.main()

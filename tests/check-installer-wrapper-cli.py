#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
WRAPPERS = (
    "install_selected_skills.sh",
    "install_recommended_codex_agents.sh",
)


class InstallerWrapperCliTests(unittest.TestCase):
    def make_fixture(self, fixture: Path) -> tuple[Path, Path]:
        repo = fixture / "repo"
        scripts = repo / "scripts"
        scripts.mkdir(parents=True)
        trace = fixture / "trace"

        for name in WRAPPERS:
            shutil.copy2(ROOT / "scripts" / name, scripts / name)

        check = scripts / "check.sh"
        check.write_text(
            f"#!/usr/bin/env bash\nprintf 'check\\n' >>{str(trace)!r}\n",
            encoding="utf-8",
        )
        check.chmod(0o755)

        backend = scripts / "install_managed_links.py"
        backend.write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "from pathlib import Path\n"
            "Path(os.environ['WRAPPER_TRACE']).open('a', encoding='utf-8').write(\n"
            "    'backend ' + ' '.join(__import__('sys').argv[1:]) + '\\n'\n"
            ")\n",
            encoding="utf-8",
        )
        return scripts, trace

    def run_wrapper(
        self,
        wrapper: Path,
        args: list[str],
        fixture: Path,
        trace: Path,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["CODEX_HOME"] = str(fixture / "codex-home")
        env["WRAPPER_TRACE"] = str(trace)
        return subprocess.run(
            [str(wrapper), *args],
            cwd=fixture,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_help_exits_zero_without_running_checks_or_backend(self):
        for flag in ("-h", "--help"):
            for wrapper_name in WRAPPERS:
                with self.subTest(flag=flag, wrapper=wrapper_name):
                    with TemporaryDirectory() as tmp:
                        fixture = Path(tmp)
                        scripts, trace = self.make_fixture(fixture)

                        result = self.run_wrapper(
                            scripts / wrapper_name,
                            [flag],
                            fixture,
                            trace,
                        )

                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertIn("Usage:", result.stdout)
                        self.assertEqual(result.stderr, "")
                        self.assertFalse(trace.exists())
                        self.assertFalse((fixture / "codex-home").exists())

    def test_invalid_invocations_exit_two_without_side_effects(self):
        invalid_args = (["--unsupported"], ["target", "extra"], ["--help", "extra"])
        for args in invalid_args:
            for wrapper_name in WRAPPERS:
                with self.subTest(args=args, wrapper=wrapper_name):
                    with TemporaryDirectory() as tmp:
                        fixture = Path(tmp)
                        scripts, trace = self.make_fixture(fixture)

                        result = self.run_wrapper(
                            scripts / wrapper_name,
                            list(args),
                            fixture,
                            trace,
                        )

                        self.assertEqual(result.returncode, 2, result)
                        self.assertEqual(result.stdout, "")
                        self.assertIn("Usage:", result.stderr)
                        self.assertFalse(trace.exists())
                        self.assertFalse((fixture / "codex-home").exists())

    def test_zero_and_one_argument_targets_retain_existing_behavior(self):
        for wrapper_name in WRAPPERS:
            target_kind = "skills" if wrapper_name == WRAPPERS[0] else "agents"
            for explicit in (False, True):
                with self.subTest(explicit=explicit, wrapper=wrapper_name):
                    with TemporaryDirectory() as tmp:
                        fixture = Path(tmp)
                        scripts, trace = self.make_fixture(fixture)
                        target = (
                            fixture / "explicit-target"
                            if explicit
                            else fixture / "codex-home" / target_kind
                        )

                        result = self.run_wrapper(
                            scripts / wrapper_name,
                            [str(target)] if explicit else [],
                            fixture,
                            trace,
                        )

                        self.assertEqual(result.returncode, 0, result.stderr)
                        lines = trace.read_text(encoding="utf-8").splitlines()
                        if wrapper_name == WRAPPERS[0]:
                            self.assertEqual(lines[0], "check")
                            backend_line = lines[1]
                        else:
                            self.assertEqual(len(lines), 1)
                            backend_line = lines[0]
                        self.assertTrue(
                            backend_line.endswith(f"--target-dir {target}"),
                            backend_line,
                        )
                        self.assertIn(f"backend {target_kind} --root ", backend_line)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "scripts" / "codex_installation_status.py"
sys.path.insert(0, str(ROOT / "scripts"))

import codex_installation_status as status_module  # noqa: E402


class CodexInstallationStatusTests(unittest.TestCase):
    @staticmethod
    def install(codex_home: Path) -> None:
        skills = codex_home / "skills"
        agents = codex_home / "agents"
        skills.mkdir(parents=True)
        agents.mkdir(parents=True)
        for source in (ROOT / "skills").iterdir():
            if source.is_symlink():
                (skills / source.name).symlink_to(source.resolve(strict=True))
        for source in (ROOT / "codex" / "agents").glob("*.toml"):
            (agents / source.name).symlink_to(source.resolve(strict=True))

    def test_json_reports_environment_home_as_healthy(self):
        with TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / "codex-home"
            self.install(codex_home)
            environment = os.environ.copy()
            environment["CODEX_HOME"] = str(codex_home)

            result = subprocess.run(
                [str(STATUS), "--json"],
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "ok")
            self.assertEqual(
                report["codex_home"],
                {"path": str(codex_home), "source": "environment"},
            )
            self.assertEqual(report["skills"]["counts"]["expected"], 18)
            self.assertEqual(report["agents"]["counts"]["expected"], 2)
            self.assertIsNone(report["rdl_command"])
            self.assertEqual(report["findings"], [])

    def test_explicit_rdl_bin_directory_is_reported(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            codex_home = fixture / "codex-home"
            bin_dir = fixture / "bin"
            bin_dir.mkdir()
            launcher = ROOT / "local" / "research-dev-loop" / "bin" / "rdl"
            (bin_dir / "rdl").symlink_to(launcher)
            self.install(codex_home)
            environment = os.environ.copy()
            environment["CODEX_HOME"] = str(codex_home)
            environment["PATH"] = os.pathsep.join((str(bin_dir), environment.get("PATH", "")))

            result = subprocess.run(
                [str(STATUS), "--rdl-bin-dir", str(bin_dir), "--json"],
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["rdl_command"]["state"], "current")
            self.assertTrue(report["rdl_command"]["on_path"])
            self.assertIsNone(report["rdl_command"]["shadowed_by"])

    def test_argument_home_precedes_environment_and_missing_links_return_two(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            argument_home = fixture / "argument-home"
            environment = os.environ.copy()
            environment["CODEX_HOME"] = str(fixture / "environment-home")

            result = subprocess.run(
                [str(STATUS), "--codex-home", str(argument_home), "--json"],
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "mismatch")
            self.assertEqual(
                report["codex_home"],
                {"path": str(argument_home), "source": "argument"},
            )
            self.assertEqual(report["skills"]["counts"]["missing"], 18)
            self.assertEqual(report["agents"]["counts"]["missing"], 2)

    def test_unset_codex_home_uses_default_under_home(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            codex_home = fixture / ".codex"
            self.install(codex_home)
            environment = os.environ.copy()
            environment.pop("CODEX_HOME", None)
            environment["HOME"] = str(fixture)

            result = subprocess.run(
                [str(STATUS), "--json"],
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["codex_home"], {"path": str(codex_home), "source": "default"})

    def test_explicit_resource_directories_report_launch_home_mismatch(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            codex_home = fixture / "codex-home"
            installed = fixture / "installed"
            self.install(installed)

            result = subprocess.run(
                [
                    str(STATUS),
                    "--codex-home",
                    str(codex_home),
                    "--skills-dir",
                    str(installed / "skills"),
                    "--agents-dir",
                    str(installed / "agents"),
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(result.stdout)
            self.assertFalse(report["skills"]["aligned"])
            self.assertFalse(report["agents"]["aligned"])
            self.assertEqual(
                {item["code"] for item in report["findings"]},
                {"skills_target_mismatch", "agents_target_mismatch"},
            )

    def test_default_text_is_compact_and_machine_readable_json_is_opt_in(self):
        with TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / "codex-home"
            self.install(codex_home)
            environment = os.environ.copy()
            environment["CODEX_HOME"] = str(codex_home)

            result = subprocess.run(
                [str(STATUS)],
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("codex-installation status=ok", result.stdout)
            self.assertIn("adapter=skills", result.stdout)
            self.assertIn("adapter=agents", result.stdout)

    def test_text_includes_rdl_section_when_explicitly_requested(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            codex_home = fixture / "codex-home"
            bin_dir = fixture / "bin"
            bin_dir.mkdir()
            launcher = ROOT / "local" / "research-dev-loop" / "bin" / "rdl"
            (bin_dir / "rdl").symlink_to(launcher)
            self.install(codex_home)
            environment = os.environ.copy()
            environment["CODEX_HOME"] = str(codex_home)
            environment["PATH"] = os.pathsep.join((str(bin_dir), "/usr/bin", "/bin"))

            result = subprocess.run(
                [str(STATUS), "--rdl-bin-dir", str(bin_dir)],
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"rdl_command target={bin_dir / 'rdl'}", result.stdout)
            self.assertIn("state=current", result.stdout)

    def test_relative_home_is_an_input_error(self):
        result = subprocess.run(
            [str(STATUS), "--codex-home", "relative-home", "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("absolute", result.stderr.lower())
        self.assertEqual(result.stdout, "")

    def test_relative_rdl_directory_is_an_input_error(self):
        result = subprocess.run(
            [str(STATUS), "--rdl-bin-dir", "relative-bin"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("absolute", result.stderr.lower())
        self.assertNotIn("traceback", result.stderr.lower())

    def test_unknown_argument_is_an_input_error(self):
        result = subprocess.run(
            [str(STATUS), "--unknown-option"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("unrecognized arguments", result.stderr.lower())

    def test_rdl_directory_off_path_is_a_mismatch(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            codex_home = fixture / "codex-home"
            bin_dir = fixture / "bin"
            bin_dir.mkdir()
            launcher = ROOT / "local" / "research-dev-loop" / "bin" / "rdl"
            (bin_dir / "rdl").symlink_to(launcher)
            self.install(codex_home)
            environment = os.environ.copy()
            environment["CODEX_HOME"] = str(codex_home)
            environment["PATH"] = "/usr/bin:/bin"

            result = subprocess.run(
                [str(STATUS), "--rdl-bin-dir", str(bin_dir), "--json"],
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(result.stdout)
            self.assertFalse(report["rdl_command"]["on_path"])
            self.assertIn("rdl_command_mismatch", {item["code"] for item in report["findings"]})

    def test_exact_owned_missing_rdl_source_is_a_combined_mismatch(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            bin_dir = fixture / "bin"
            missing_source = fixture / "missing-rdl"
            bin_dir.mkdir()
            (bin_dir / "rdl").symlink_to(missing_source)
            base_report = {
                "status": "ok",
                "codex_home": {},
                "skills": {},
                "agents": {},
                "rdl_command": None,
                "findings": [],
            }
            output = io.StringIO()
            safe_path = os.pathsep.join((str(bin_dir), "/usr/bin", "/bin"))

            with (
                mock.patch.object(
                    status_module,
                    "build_report",
                    return_value=base_report,
                ),
                mock.patch.object(
                    status_module,
                    "canonical_source",
                    return_value=missing_source,
                ),
                mock.patch.dict(os.environ, {"PATH": safe_path}),
                redirect_stdout(output),
            ):
                result = status_module.run(
                    ["--rdl-bin-dir", str(bin_dir), "--json"]
                )

            report = json.loads(output.getvalue())
            self.assertEqual(result, 2)
            self.assertEqual(report["status"], "mismatch")
            self.assertEqual(report["rdl_command"]["state"], "current")
            self.assertFalse(report["rdl_command"]["source_available"])
            self.assertIn(
                "rdl_command_mismatch",
                {item["code"] for item in report["findings"]},
            )


if __name__ == "__main__":
    unittest.main()

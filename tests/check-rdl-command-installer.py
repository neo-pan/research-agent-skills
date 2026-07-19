#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install_rdl_command.py"
SOURCE = ROOT / "local" / "research-dev-loop" / "bin" / "rdl"
START = {
    "mode": "research",
    "mission": {
        "objective": "Exercise the installed RDL adapter.",
        "scope": ["portable CLI fixture"],
        "out_of_scope": [],
        "success_criteria": ["state is recoverable"],
        "invariants": [],
        "abort_criteria": [],
    },
}


class InstallerFixture:
    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home with spaces"
        self.bin = self.home / ".local" / "bin"
        self.project = root / "unrelated project"
        self.home.mkdir(mode=0o700)
        self.bin.mkdir(parents=True, mode=0o700)
        self.project.mkdir()
        self.path = os.pathsep.join((str(self.bin), str(Path(sys.executable).parent), "/usr/bin"))

    @property
    def target(self) -> Path:
        return self.bin / "rdl"

    def environment(self, *, path: str | None = None) -> dict[str, str]:
        env = os.environ.copy()
        env.update(HOME=str(self.home), PATH=self.path if path is None else path)
        env.pop("PYTHONPATH", None)
        env.pop("RDL_BIN_DIR", None)
        return env

    def run(
        self,
        action: str,
        *,
        bin_dir: Path | None = None,
        path: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(INSTALLER), action, "--bin-dir", str(bin_dir or self.bin)],
            cwd=self.project,
            env=self.environment(path=path),
            text=True,
            capture_output=True,
            check=False,
        )


class RdlCommandInstallerTests(unittest.TestCase):
    def test_clean_install_status_and_uninstall_are_idempotent(self):
        with TemporaryDirectory(prefix="rdl adapter ") as tmp:
            fixture = InstallerFixture(Path(tmp))

            installed = fixture.run("install")
            repeated = fixture.run("install")
            status = fixture.run("status")
            removed = fixture.run("uninstall")
            removed_again = fixture.run("uninstall")

            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertIn("installed", installed.stdout.lower())
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertIn("unchanged", repeated.stdout.lower())
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("current", status.stdout.lower())
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertEqual(removed_again.returncode, 0, removed_again.stderr)
            self.assertFalse(os.path.lexists(fixture.target))

    def test_real_adapter_runs_start_and_handoff_from_unrelated_cwd(self):
        with TemporaryDirectory(prefix="rdl runtime ") as tmp:
            fixture = InstallerFixture(Path(tmp))
            shell_rc = fixture.home / ".bashrc"
            shell_rc.write_text("user-owned\n", encoding="utf-8")
            self.assertEqual(fixture.run("install").returncode, 0)

            started = subprocess.run(
                ["rdl", "start", "--input", "-"],
                cwd=fixture.project,
                env=fixture.environment(),
                input=json.dumps(START),
                text=True,
                capture_output=True,
                check=False,
            )
            handed_off = subprocess.run(
                ["rdl", "handoff"],
                cwd=fixture.project,
                env=fixture.environment(),
                text=True,
                capture_output=True,
                check=False,
            )
            removed = fixture.run("uninstall")

            self.assertEqual(started.returncode, 0, started.stderr)
            self.assertEqual(json.loads(started.stdout)["status"], "ok")
            self.assertEqual(handed_off.returncode, 0, handed_off.stderr)
            self.assertEqual(json.loads(handed_off.stdout)["status"], "ok")
            self.assertEqual(removed.returncode, 0, removed.stderr)
            self.assertTrue((fixture.project / ".rdl").is_dir())
            self.assertEqual(shell_rc.read_text(encoding="utf-8"), "user-owned\n")

    def test_install_never_replaces_existing_targets(self):
        factories = {
            "file": lambda target, fixture: target.write_text("user-owned\n", encoding="utf-8"),
            "directory": lambda target, fixture: target.mkdir(),
            "unrelated symlink": lambda target, fixture: target.symlink_to(fixture.root / "elsewhere"),
            "broken symlink": lambda target, fixture: target.symlink_to(fixture.root / "missing"),
            "relative same-source symlink": lambda target, fixture: target.symlink_to(
                os.path.relpath(SOURCE, target.parent)
            ),
        }
        for label, create in factories.items():
            with self.subTest(label=label), TemporaryDirectory() as tmp:
                fixture = InstallerFixture(Path(tmp))
                create(fixture.target, fixture)
                before = os.readlink(fixture.target) if fixture.target.is_symlink() else None

                result = fixture.run("install")

                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertTrue(os.path.lexists(fixture.target))
                if before is not None:
                    self.assertEqual(os.readlink(fixture.target), before)

    def test_uninstall_removes_only_exact_current_link(self):
        with TemporaryDirectory() as tmp:
            fixture = InstallerFixture(Path(tmp))
            fixture.target.symlink_to(os.path.relpath(SOURCE, fixture.target.parent))

            refused = fixture.run("uninstall")

            self.assertEqual(refused.returncode, 2, refused.stderr)
            self.assertTrue(fixture.target.is_symlink())
            self.assertNotEqual(os.readlink(fixture.target), str(SOURCE))

    def test_cyclic_symlink_is_reported_as_broken_without_mutation(self):
        with TemporaryDirectory() as tmp:
            fixture = InstallerFixture(Path(tmp))
            fixture.target.symlink_to(fixture.target.name)

            status = fixture.run("status")
            installed = fixture.run("install")
            removed = fixture.run("uninstall")

            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("state=broken", status.stdout)
            self.assertEqual(installed.returncode, 2, installed.stderr)
            self.assertIn("broken target", installed.stderr)
            self.assertEqual(removed.returncode, 2, removed.stderr)
            self.assertIn("broken target", removed.stderr)
            self.assertTrue(fixture.target.is_symlink())
            self.assertEqual(os.readlink(fixture.target), fixture.target.name)

    def test_status_works_with_unsafe_path_and_read_only_directory(self):
        with TemporaryDirectory() as tmp:
            fixture = InstallerFixture(Path(tmp))
            fixture.target.symlink_to(SOURCE)
            fixture.bin.chmod(0o500)
            unsafe_path = os.pathsep.join((".", str(Path(sys.executable).parent), "/usr/bin"))
            try:
                result = fixture.run("status", path=unsafe_path)
            finally:
                fixture.bin.chmod(0o700)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("current", result.stdout.lower())
            self.assertIn("unsafe", result.stdout.lower())

    def test_uninstall_does_not_depend_on_path_safety(self):
        with TemporaryDirectory() as tmp:
            fixture = InstallerFixture(Path(tmp))
            fixture.target.symlink_to(SOURCE)

            result = fixture.run(
                "uninstall",
                path=os.pathsep.join((".", str(Path(sys.executable).parent), "/usr/bin")),
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(os.path.lexists(fixture.target))

    def test_only_executable_earlier_command_counts_as_shadow(self):
        with TemporaryDirectory() as tmp:
            fixture = InstallerFixture(Path(tmp))
            earlier = fixture.root / "earlier"
            earlier.mkdir()
            inert = earlier / "rdl"
            inert.write_text("not executable\n", encoding="utf-8")
            path = os.pathsep.join((str(earlier), fixture.path))

            allowed = fixture.run("install", path=path)
            self.assertEqual(allowed.returncode, 0, allowed.stderr)
            self.assertTrue(fixture.target.is_symlink())

        with TemporaryDirectory() as tmp:
            fixture = InstallerFixture(Path(tmp))
            earlier = fixture.root / "earlier"
            earlier.mkdir()
            executable = earlier / "rdl"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            path = os.pathsep.join((str(earlier), fixture.path))

            blocked = fixture.run("install", path=path)
            self.assertEqual(blocked.returncode, 2, blocked.stderr)
            self.assertIn("shadow", blocked.stderr.lower())
            self.assertFalse(os.path.lexists(fixture.target))

    def test_mutation_requires_private_user_bin_inside_home(self):
        with TemporaryDirectory() as tmp:
            fixture = InstallerFixture(Path(tmp))
            outside = fixture.root / "outside"
            outside.mkdir(mode=0o700)
            outside_path = os.pathsep.join((str(outside), fixture.path))
            outside_result = fixture.run("install", bin_dir=outside, path=outside_path)

            fixture.bin.chmod(0o777)
            try:
                public_result = fixture.run("install")
            finally:
                fixture.bin.chmod(0o700)

            system_result = fixture.run(
                "install",
                bin_dir=Path("/usr/bin"),
                path=os.pathsep.join((str(Path(sys.executable).parent), "/usr/bin")),
            )

            self.assertEqual(outside_result.returncode, 2, outside_result.stderr)
            self.assertEqual(public_result.returncode, 2, public_result.stderr)
            self.assertEqual(system_result.returncode, 2, system_result.stderr)
            self.assertFalse((outside / "rdl").exists())

    def test_explicit_bin_directory_must_be_absolute_and_on_path_for_install(self):
        with TemporaryDirectory() as tmp:
            fixture = InstallerFixture(Path(tmp))
            relative = fixture.run("status", bin_dir=Path("relative-bin"))
            off_path = fixture.root / "off path"
            off_path.mkdir(mode=0o700)
            off_path_result = fixture.run("install", bin_dir=off_path)

            self.assertEqual(relative.returncode, 1, relative.stderr)
            self.assertEqual(off_path_result.returncode, 2, off_path_result.stderr)
            self.assertFalse((off_path / "rdl").exists())

    def test_concurrent_installers_converge_without_overwrite(self):
        with TemporaryDirectory() as tmp:
            fixture = InstallerFixture(Path(tmp))
            command = [str(INSTALLER), "install", "--bin-dir", str(fixture.bin)]
            processes = [
                subprocess.Popen(
                    command,
                    cwd=fixture.project,
                    env=fixture.environment(),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for _ in range(2)
            ]
            results = [process.communicate(timeout=10) + (process.returncode,) for process in processes]

            self.assertEqual([result[2] for result in results], [0, 0], results)
            self.assertEqual(os.readlink(fixture.target), str(SOURCE))
            self.assertTrue(any("unchanged" in result[0].lower() for result in results))


if __name__ == "__main__":
    unittest.main()

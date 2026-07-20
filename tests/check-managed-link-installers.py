#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
AGENT_INSTALLER = ROOT / "scripts" / "install_recommended_codex_agents.sh"
sys.path.insert(0, str(ROOT / "scripts"))

from lib import managed_links  # noqa: E402


class ManagedLinkInstallerTests(unittest.TestCase):
    @staticmethod
    def run_installer(installer: Path, target: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(installer), str(target)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    @staticmethod
    def skill_installer_fixture(fixture: Path) -> tuple[Path, Path]:
        repo = fixture / "repo"
        scripts = repo / "scripts"
        library = scripts / "lib"
        source = repo / "local" / "demo"
        library.mkdir(parents=True)
        source.mkdir(parents=True)
        (repo / "skills").mkdir()
        (repo / "skills" / "demo").symlink_to(source)
        (source / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
        (repo / "selected-skills.conf").write_text(
            '[upstream "mattpocock"]\n'
            "    path = upstream/mattpocock-skills\n\n"
            "[local]\n"
            "    skill = local/demo\n",
            encoding="utf-8",
        )
        for path in (
            ROOT / "scripts" / "install_selected_skills.sh",
            ROOT / "scripts" / "install_managed_links.py",
            ROOT / "scripts" / "lib" / "__init__.py",
            ROOT / "scripts" / "lib" / "managed_links.py",
            ROOT / "scripts" / "lib" / "repository_links.py",
        ):
            destination = scripts / path.relative_to(ROOT / "scripts")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        check = scripts / "check.sh"
        check.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        check.chmod(0o755)
        return scripts / "install_selected_skills.sh", repo

    def test_unprepared_skill_set_is_refused_without_pruning(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            installer, repo = self.skill_installer_fixture(fixture)
            (repo / "skills" / "demo").unlink()
            target = fixture / "installed-skills"
            target.mkdir()
            managed = target / "retired"
            managed.symlink_to(repo / "local" / "retired")

            result = subprocess.run(
                [str(installer), str(target)],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("do not match selected-skills.conf", result.stderr)
            self.assertTrue(managed.is_symlink())

    def test_empty_agent_source_is_refused_without_pruning(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            repo = fixture / "repo"
            (repo / "codex" / "agents").mkdir(parents=True)
            target = fixture / "installed-agents"
            target.mkdir()
            managed = target / "retired.toml"
            managed.symlink_to(repo / "codex" / "agents" / "retired.toml")

            result = subprocess.run(
                [
                    str(ROOT / "scripts" / "install_managed_links.py"),
                    "agents",
                    "--root",
                    str(repo),
                    "--target-dir",
                    str(target),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("no recommended Codex agent configs", result.stderr)
            self.assertTrue(managed.is_symlink())

    def test_install_batch_stays_bound_to_locked_directory_after_path_replacement(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            target = fixture / "target"
            moved = fixture / "moved"
            owned_root = fixture / "repo" / "codex" / "agents"
            target.mkdir()
            owned_root.mkdir(parents=True)
            retired = target / "retired.toml"
            retired.symlink_to(owned_root / "retired.toml")
            foreign_source = fixture / "foreign-source"
            original_plan = managed_links._plan_at

            def replace_path_after_plan(directory_fd, desired, owned_roots):
                actions = original_plan(directory_fd, desired, owned_roots)
                target.rename(moved)
                target.mkdir()
                (target / "retired.toml").symlink_to(foreign_source)
                return actions

            with mock.patch.object(
                managed_links,
                "_plan_at",
                side_effect=replace_path_after_plan,
            ):
                result = managed_links.install_batch(target, {}, (owned_root,))

            self.assertEqual(result.pruned, 1)
            self.assertFalse(os.path.lexists(moved / "retired.toml"))
            self.assertEqual(os.readlink(target / "retired.toml"), str(foreign_source))

    def test_prune_revalidates_planned_link_before_unlink(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            target = fixture / "target"
            owned_root = fixture / "repo" / "codex" / "agents"
            target.mkdir()
            owned_root.mkdir(parents=True)
            retired = target / "retired.toml"
            retired.symlink_to(owned_root / "retired.toml")
            planned = managed_links.LinkState(
                "symlink",
                "current-checkout",
                "broken",
                str(owned_root / "retired.toml"),
            )
            changed = managed_links.LinkState(
                "symlink",
                "foreign",
                "broken",
                str(fixture / "foreign"),
            )

            with mock.patch.object(
                managed_links,
                "inspect_link_at",
                side_effect=(planned, changed),
            ):
                with self.assertRaises(managed_links.ManagedLinkError):
                    managed_links.install_batch(target, {}, (owned_root,))

            self.assertTrue(retired.is_symlink())

    def test_replace_revalidates_actual_link_before_unlink(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            target = fixture / "target"
            owned_root = fixture / "repo" / "codex" / "agents"
            desired_source = owned_root / "reviewer.toml"
            target.mkdir()
            owned_root.mkdir(parents=True)
            desired_source.write_text("current\n", encoding="utf-8")
            installed = target / "reviewer.toml"
            installed.symlink_to(owned_root / "retired-reviewer.toml")
            foreign_source = fixture / "foreign-reviewer.toml"
            original_plan = managed_links._plan_at

            def replace_link_after_plan(directory_fd, desired, owned_roots):
                actions = original_plan(directory_fd, desired, owned_roots)
                installed.unlink()
                installed.symlink_to(foreign_source)
                return actions

            with mock.patch.object(
                managed_links,
                "_plan_at",
                side_effect=replace_link_after_plan,
            ):
                with self.assertRaises(managed_links.ManagedLinkError):
                    managed_links.install_batch(
                        target,
                        {installed.name: desired_source},
                        (owned_root,),
                    )

            self.assertEqual(os.readlink(installed), str(foreign_source))

    def test_create_preserves_target_that_appears_during_symlink_creation(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            target = fixture / "target"
            source = fixture / "repo" / "codex" / "agents" / "reviewer.toml"
            foreign_source = fixture / "foreign-reviewer.toml"
            target.mkdir()
            source.parent.mkdir(parents=True)
            source.write_text("current\n", encoding="utf-8")
            original_symlink = os.symlink

            def create_foreign_first(source_text, name, *, dir_fd=None):
                original_symlink(str(foreign_source), name, dir_fd=dir_fd)
                return original_symlink(source_text, name, dir_fd=dir_fd)

            with mock.patch.object(
                managed_links.os,
                "symlink",
                side_effect=create_foreign_first,
            ):
                with self.assertRaises(managed_links.ManagedLinkError):
                    managed_links.install_batch(
                        target,
                        {"reviewer.toml": source},
                        (source.parent,),
                    )

            self.assertEqual(
                os.readlink(target / "reviewer.toml"),
                str(foreign_source),
            )

    def test_skill_install_refuses_foreign_symlink_without_mutation(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            installer, repo = self.skill_installer_fixture(fixture)
            target = fixture / "skills"
            foreign = fixture / "foreign"
            target.mkdir()
            foreign.mkdir()
            conflict = target / "demo"
            conflict.symlink_to(foreign)
            before = os.readlink(conflict)

            result = subprocess.run(
                [str(installer), str(target)],
                cwd=repo,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("foreign", result.stderr.lower())
            self.assertTrue(conflict.is_symlink())
            self.assertEqual(os.readlink(conflict), before)

    def test_agent_install_refuses_foreign_symlink_without_partial_mutation(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            target = fixture / "agents"
            foreign = fixture / "foreign.toml"
            target.mkdir()
            foreign.write_text("foreign\n", encoding="utf-8")
            conflict = target / "rdl-reviewer.toml"
            conflict.symlink_to(foreign)
            before = os.readlink(conflict)

            result = self.run_installer(AGENT_INSTALLER, target)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("foreign", result.stderr.lower())
            self.assertTrue(conflict.is_symlink())
            self.assertEqual(os.readlink(conflict), before)
            self.assertFalse((target / "rdl-explorer.toml").exists())

    def test_relative_equivalent_link_is_foreign(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "agents"
            target.mkdir()
            source = ROOT / "codex" / "agents" / "rdl-reviewer.toml"
            conflict = target / source.name
            conflict.symlink_to(os.path.relpath(source, target))
            before = os.readlink(conflict)

            result = self.run_installer(AGENT_INSTALLER, target)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("ownership=foreign", result.stderr)
            self.assertEqual(os.readlink(conflict), before)

    def test_foreign_broken_link_is_preserved(self):
        with TemporaryDirectory() as tmp:
            fixture = Path(tmp)
            target = fixture / "agents"
            target.mkdir()
            conflict = target / "rdl-reviewer.toml"
            conflict.symlink_to(fixture / "historical-checkout" / "rdl-reviewer.toml")
            before = os.readlink(conflict)

            result = self.run_installer(AGENT_INSTALLER, target)

            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("ownership=foreign", result.stderr)
            self.assertIn("health=broken", result.stderr)
            self.assertTrue(conflict.is_symlink())
            self.assertEqual(os.readlink(conflict), before)

    def test_current_checkout_agent_links_are_replaced_or_pruned(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "agents"
            target.mkdir()
            reviewer = target / "rdl-reviewer.toml"
            reviewer.symlink_to(ROOT / "codex" / "agents" / "retired-reviewer.toml")
            stale = target / "retired-agent.toml"
            stale.symlink_to(ROOT / "codex" / "agents" / "retired-agent.toml")

            result = self.run_installer(AGENT_INSTALLER, target)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                os.readlink(reviewer),
                str((ROOT / "codex" / "agents" / "rdl-reviewer.toml").resolve()),
            )
            self.assertFalse(os.path.lexists(stale))
            self.assertIn("replaced=1", result.stdout)
            self.assertIn("pruned=1", result.stdout)

    def test_repeated_agent_install_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "agents"

            installed = self.run_installer(AGENT_INSTALLER, target)
            repeated = self.run_installer(AGENT_INSTALLER, target)

            self.assertEqual(installed.returncode, 0, installed.stderr)
            self.assertIn("created=2", installed.stdout)
            self.assertEqual(repeated.returncode, 0, repeated.stderr)
            self.assertIn("unchanged=2", repeated.stdout)

    def test_concurrent_agent_installs_converge(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "agents"
            command = [str(AGENT_INSTALLER), str(target)]
            processes = [
                subprocess.Popen(
                    command,
                    cwd=ROOT,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for _ in range(2)
            ]
            results = [
                process.communicate(timeout=15) + (process.returncode,)
                for process in processes
            ]

            self.assertEqual([item[2] for item in results], [0, 0], results)
            for source in (ROOT / "codex" / "agents").glob("*.toml"):
                self.assertEqual(os.readlink(target / source.name), str(source.resolve()))


if __name__ == "__main__":
    unittest.main()

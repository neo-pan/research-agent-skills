#!/usr/bin/env python3

from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]


class LinkGenerationConcurrencyTests(unittest.TestCase):
    def test_concurrent_generators_preserve_the_selected_skills_view(self):
        with TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            scripts = repo / "scripts"
            library = scripts / "lib"
            local_skill = repo / "local" / "demo"
            upstream = repo / "upstream" / "mattpocock-skills"
            skills = repo / "skills"

            library.mkdir(parents=True)
            local_skill.mkdir(parents=True)
            upstream.mkdir(parents=True)
            skills.mkdir()

            shutil.copy2(ROOT / "scripts" / "link_selected_skills.sh", scripts)
            shutil.copy2(
                ROOT / "scripts" / "lib" / "selected_skills.sh",
                library,
            )
            (upstream / ".git").write_text("gitdir: unused\n", encoding="utf-8")
            skill_definition = local_skill / "SKILL.md"
            skill_definition.write_text("---\nname: demo\n---\n", encoding="utf-8")
            (repo / "selected-skills.conf").write_text(
                '[upstream "mattpocock"]\n'
                "    path = upstream/mattpocock-skills\n\n"
                "[local]\n"
                "    skill = local/demo\n",
                encoding="utf-8",
            )
            (skills / ".gitkeep").touch()

            for index in range(2_000):
                (skills / f"stale-{index:04d}").symlink_to(local_skill)

            source_before = skill_definition.read_bytes()
            read_fd, write_fd = os.pipe()
            processes: list[subprocess.Popen[str]] = []
            try:
                for _ in range(12):
                    processes.append(
                        subprocess.Popen(
                            [
                                "bash",
                                "-c",
                                f'IFS= read -r -n 1 <&{read_fd}; exec "$1"',
                                "bash",
                                str(scripts / "link_selected_skills.sh"),
                            ],
                            cwd=repo,
                            pass_fds=(read_fd,),
                            text=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        )
                    )
                os.close(read_fd)
                read_fd = -1
                os.write(write_fd, b"x" * len(processes))
            finally:
                os.close(write_fd)

            results = [process.communicate(timeout=30) for process in processes]
            failures = [
                {
                    "index": index,
                    "returncode": process.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                }
                for index, (process, (stdout, stderr)) in enumerate(
                    zip(processes, results)
                )
                if process.returncode != 0
            ]

            self.assertEqual(skill_definition.read_bytes(), source_before)
            failure_summary = [
                {
                    "index": failure["index"],
                    "returncode": failure["returncode"],
                    "stderr_first_line": next(
                        iter(failure["stderr"].splitlines()), ""
                    ),
                }
                for failure in failures
            ]
            self.assertEqual(failure_summary, [])
            self.assertEqual(
                sorted(path.name for path in skills.iterdir()),
                [".gitkeep", "demo"],
            )
            self.assertTrue((skills / "demo").is_symlink())
            self.assertEqual((skills / "demo").resolve(), local_skill.resolve())


if __name__ == "__main__":
    unittest.main()

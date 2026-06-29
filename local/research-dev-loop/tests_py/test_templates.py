import tempfile
import unittest
from pathlib import Path

from rdl import templates
from rdl.model import SessionMode


class TemplateTests(unittest.TestCase):
    def test_render_research_prompt_matches_protocol_fields(self):
        text = templates.render_prompt(
            SessionMode.RESEARCH,
            2,
            "Continue research session r1",
            "continue; closes claim; recommended next loop build",
        )

        self.assertIn("<!-- rdl:managed policy=managed_prefix -->", text)
        self.assertIn("# Round 2 Prompt", text)
        self.assertIn("Mode: research", text)
        self.assertIn("Objective: Continue research session r1", text)
        self.assertIn("Previous Decision: continue; closes claim; recommended next loop build", text)
        self.assertIn("Required Files: prompt.md, evidence.md, interpretation.md, review.md, decision.md", text)
        self.assertIn("Expected Exit Decision: claim decision with evidence and uncertainty", text)
        self.assertTrue(text.endswith("\n"))

    def test_render_build_prompt_uses_build_required_files_and_exit_decision(self):
        text = templates.render_prompt("build", 1, "mission.md", "none")

        self.assertIn("# Round 1 Prompt", text)
        self.assertIn("Mode: build", text)
        self.assertIn("Required Files: prompt.md, intent.md, work.md, evidence.md, review.md, decision.md", text)
        self.assertIn("Expected Exit Decision: capability decision with verification evidence", text)

    def test_template_path_rejects_unknown_template(self):
        with self.assertRaises(FileNotFoundError):
            templates.template_path("missing-template.md")

    def test_copy_template_writes_destination_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "rounds" / "001" / "review.md"

            templates.copy_template("review.md", destination)

            self.assertTrue(destination.is_file())
            self.assertIn("Reviewer:", destination.read_text(encoding="utf-8"))

    def test_write_prompt_writes_rendered_prompt_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "rounds" / "002" / "prompt.md"

            templates.write_prompt(destination, "research", 2, "Continue research", "continue")

            self.assertTrue(destination.is_file())
            text = destination.read_text(encoding="utf-8")
            self.assertIn("# Round 2 Prompt", text)
            self.assertIn("Objective: Continue research", text)


if __name__ == "__main__":
    unittest.main()

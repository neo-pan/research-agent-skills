import tempfile
import unittest
from pathlib import Path

from rdl import templates
from rdl.model import SessionMode
from rdl.protocol import descriptor


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
        self.assertIn(f"Required Files: {', '.join(descriptor.completed_round_files(SessionMode.RESEARCH))}", text)
        self.assertIn(f"Expected Exit Decision: {descriptor.prompt_expected_exit_decision(SessionMode.RESEARCH)}", text)
        self.assertTrue(text.endswith("\n"))

    def test_render_build_prompt_uses_build_required_files_and_exit_decision(self):
        text = templates.render_prompt("build", 1, "mission.md", "none")

        self.assertIn("# Round 1 Prompt", text)
        self.assertIn("Mode: build", text)
        self.assertIn(f"Required Files: {', '.join(descriptor.completed_round_files(SessionMode.BUILD))}", text)
        self.assertIn(f"Expected Exit Decision: {descriptor.prompt_expected_exit_decision(SessionMode.BUILD)}", text)

    def test_render_prompt_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            templates.render_prompt("deploy", 1, "mission.md", "none")

    def test_template_path_rejects_unknown_template(self):
        with self.assertRaises(FileNotFoundError):
            templates.template_path("missing-template.md")

    def test_markdown_templates_expose_required_protocol_shape(self):
        checks = (
            ("review.md", "review", "fields"),
            ("decision.md", "decision", "fields"),
            ("final-report.md", "final-report", "sections"),
            ("progress.md", "progress", "sections"),
        )
        for template_name, kind, shape in checks:
            with self.subTest(template=template_name):
                text = templates.template_path(template_name).read_text(encoding="utf-8")
                if shape == "fields":
                    for field in descriptor.required_fields(kind):
                        self.assertIn(f"{field}:", text)
                else:
                    for section in descriptor.required_sections(kind):
                        self.assertIn(f"## {section}\n", text)

    def test_copy_template_writes_destination_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "rounds" / "001" / "review.md"

            templates.copy_template("review.md", destination)

            self.assertTrue(destination.is_file())
            self.assertIn("Reviewer:", destination.read_text(encoding="utf-8"))

    def test_initialize_session_files_uses_protocol_template_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mission = root / "source-mission.md"
            session_dir = root / "session"
            mission.write_text("# Mission\n\nFixture.\n", encoding="utf-8")

            templates.initialize_session_files(session_dir, mission)

            self.assertEqual((session_dir / "mission.md").read_text(encoding="utf-8"), mission.read_text(encoding="utf-8"))
            for name in descriptor.initialized_session_templates():
                with self.subTest(template=name):
                    self.assertTrue((session_dir / name).is_file())
            self.assertFalse((session_dir / "state.json").exists())
            self.assertFalse((session_dir / "final-report.md").exists())

    def test_write_prompt_writes_rendered_prompt_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "rounds" / "002" / "prompt.md"

            templates.write_prompt(destination, "research", 2, "Continue research", "continue")

            self.assertTrue(destination.is_file())
            text = destination.read_text(encoding="utf-8")
            self.assertIn("# Round 2 Prompt", text)
            self.assertIn("Objective: Continue research", text)

    def test_write_decision_populates_decision_type_and_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "rounds" / "001" / "decision.md"

            templates.write_decision(destination, "continue", "claim")

            text = destination.read_text(encoding="utf-8")
            self.assertIn("Decision: continue", text)
            self.assertIn("Closes: claim", text)
            self.assertIn("Recommended next loop: research | build | none", text)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEMANTIC = ROOT / "local" / "research-dev-loop" / "SEMANTIC_REVIEW.md"
PREPARATION = ROOT / "local" / "research-dev-loop" / "PRE_REVIEW_PREPARATION.md"
REVIEWER = ROOT / "codex" / "agents" / "rdl-reviewer.toml"
EXPLORER = ROOT / "codex" / "agents" / "rdl-explorer.toml"
ORCHESTRATOR = ROOT / "local" / "rdl-orchestrator" / "CODEX.md"
README = ROOT / "README.md"
sys.path.insert(0, str(ROOT / "local" / "research-dev-loop"))

from rdl.model import SEVERITIES, VERDICTS  # noqa: E402


EXPECTED_TASK = (
    "You are the configured independent RDL semantic reviewer. Review only the supplied "
    "review-pack JSON. Do not use tools, inspect files, rely on parent context, or infer "
    "unstated external facts. Copy the supplied action, subject_digest, and adapter label "
    "exactly. Return only one JSON object matching the supplied output schema, with no "
    "Markdown fence or extra text. Use the relevant progress key as finding.category when "
    "it identifies a defect."
)
# This is the calibrated raw-review interface. Changing it requires deliberate
# contract review and may trigger the three-run semantic fallback.
EXPECTED_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "subject_digest", "adapter", "verdict", "findings"],
    "properties": {
        "action": {"enum": ["next", "close"]},
        "subject_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "adapter": {"type": "string", "minLength": 1},
        "verdict": {
            "enum": ["pass", "pass_with_notes", "revise", "block", "inconclusive"]
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "category", "claim", "required_resolution"],
                "properties": {
                    "severity": {"enum": ["blocking", "warning", "note"]},
                    "category": {"type": "string", "minLength": 1},
                    "claim": {"type": "string", "minLength": 1},
                    "required_resolution": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}


def fenced(text: str, language: str) -> str:
    matches = re.findall(rf"```{language}\n(.*?)\n```", text, flags=re.DOTALL)
    if len(matches) != 1:
        raise AssertionError(f"expected one {language} fence, found {len(matches)}")
    return matches[0]


class ReviewContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SEMANTIC.read_text(encoding="utf-8")
        cls.task = fenced(cls.text, "text")
        cls.schema = json.loads(fenced(cls.text, "json"))

    def test_task_matches_calibrated_prompt(self):
        self.assertEqual(self.task, EXPECTED_TASK)

    def test_raw_schema_matches_calibrated_contract(self):
        self.assertEqual(self.schema, EXPECTED_SCHEMA)

    def test_raw_schema_uses_current_rdl_vocab(self):
        properties = self.schema["properties"]
        self.assertEqual(set(properties["verdict"]["enum"]), set(VERDICTS))
        finding_properties = properties["findings"]["items"]["properties"]
        self.assertEqual(set(finding_properties["severity"]["enum"]), set(SEVERITIES))
        self.assertNotIn("disposition", finding_properties)
        self.assertNotIn("rationale", finding_properties)

    def test_adapter_failure_and_main_adjudication_are_explicit(self):
        self.assertIn("this task, schema, pack, and adapter label", self.text)
        self.assertNotIn("named artifacts", self.text)
        self.assertIn("Use native schema or inline it", self.text)
        self.assertIn("Invalid output is an adapter failure", self.text)
        self.assertIn("retry unchanged without applying it", self.text)
        self.assertIn("adds `disposition` and `rationale`", self.text)
        self.assertIn("One valid review is allowed per action/digest", self.text)

    def test_every_reviewer_entrypoint_is_pack_only(self):
        for path in (SEMANTIC, REVIEWER, ORCHESTRATOR, README):
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text(encoding="utf-8").lower()
                self.assertNotIn("verification artifacts", text)
                self.assertIn("review pack", text.replace("review-pack", "review pack"))
        reviewer = REVIEWER.read_text(encoding="utf-8")
        self.assertIn("Do not use tools or inspect files", reviewer)
        self.assertIn("digest-bound receipt or excerpt", reviewer)
        orchestrator = " ".join(ORCHESTRATOR.read_text(encoding="utf-8").split())
        self.assertIn("digest-bound receipt or excerpt", orchestrator)

    def test_pre_review_preparation_reuses_the_existing_review_seam(self):
        preparation = PREPARATION.read_text(encoding="utf-8")
        semantic = SEMANTIC.read_text(encoding="utf-8")
        orchestrator = ORCHESTRATOR.read_text(encoding="utf-8")
        explorer = EXPLORER.read_text(encoding="utf-8")

        self.assertIn("PRE_REVIEW_PREPARATION.md", semantic)
        self.assertIn("PRE_REVIEW_PREPARATION.md", orchestrator)
        identity_gate = (
            "Verify observed size_bytes and sha256 against the registered identity "
            "before opening, reading, inspecting, or excerpting content"
        )
        for text in (preparation, explorer):
            normalized = " ".join(text.split())
            self.assertIn("registered artifact IDs and paths", text)
            self.assertIn(identity_gate, normalized)
            self.assertNotIn("Before citing content", normalized)
            self.assertIn("match count, truncation, and zero-match scope", text)
        self.assertIn("reviewer_task.questions", preparation)
        self.assertIn("mission.success_criteria", preparation)
        self.assertIn("action_context", preparation)
        self.assertIn("one bounded snapshot receipt", preparation)
        self.assertIn("workflow template, not a schema or readiness gate", preparation)
        self.assertIn("semantic reviewer", preparation)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from rdl.cli import main
from rdl.engine import RdlEngine


START = {
    "mode": "research",
    "mission": {
        "objective": "Determine whether the candidate is supported.",
        "scope": ["bounded fixture"],
        "out_of_scope": ["deployment"],
        "success_criteria": ["decision cites direct evidence"],
        "invariants": ["preserve uncertainty"],
        "abort_criteria": ["required evidence is unavailable"],
    },
}


def routine_delta(version: int = 1, *, transition: str = "next", outcome: str | None = None, risk: str = "routine"):
    decision = {
        "kind": "continue" if risk == "routine" else "accept",
        "subject": "fixture claim",
        "evidence_refs": ["result"],
        "uncertainty": "bounded fixture uncertainty",
        "remaining_unknowns": ["larger workloads"],
        "next_step": "run the next bounded check",
        "recommended_transition": transition,
    }
    if transition == "close":
        decision["close_outcome"] = outcome or "positive"
    return {
        "expected_state_version": version,
        "risk": risk,
        "artifacts": {
            "report": {
                "kind": "report",
                "path": "artifacts/report.json",
                "description": "fixture verification receipt",
                "stability": "snapshot",
                "verifier": {"name": "fixture", "status": "passed", "summary": "direct check passed"},
            }
        },
        "evidence": {
            "result": {
                "claim": "fixture claim",
                "summary": "the direct fixture check passed",
                "bearing": "supports",
                "strength": "strong",
                "artifact_refs": ["report"],
                "uncertainty": "one bounded fixture",
            }
        },
        "progress_updates": {
            "fixture": {
                "status": "completed",
                "summary": "fixture verification completed",
                "blocking": False,
                "evidence_refs": ["result"],
            }
        },
        "interpretation": {
            "shows": ["the fixture behaves as claimed"],
            "does_not_show": ["production scale"],
            "uncertainty": ["larger workloads are untested"],
            "implications": ["advance the bounded investigation"],
        },
        "decision": decision,
    }


def review_result(version: int, digest: str, *, action: str = "close", verdict: str = "pass"):
    return {
        "expected_state_version": version,
        "risk": "routine",
        "review_result": {
            "action": action,
            "subject_digest": digest,
            "adapter": "fixture-reviewer",
            "verdict": verdict,
            "findings": [],
        },
    }


@contextmanager
def project():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "artifacts").mkdir()
        (root / "artifacts" / "report.json").write_text('{"passed":true}\n', encoding="utf-8")
        yield root, RdlEngine(root)


def run_cli(root: Path, argv: list[str], stdin: dict | None = None):
    output = StringIO()
    input_stream = StringIO(json.dumps(stdin)) if stdin is not None else StringIO()
    old = Path.cwd()
    os.chdir(root)
    try:
        with patch("sys.stdout", output), patch("sys.stdin", input_stream):
            code = main(argv)
    finally:
        os.chdir(old)
    return code, json.loads(output.getvalue())

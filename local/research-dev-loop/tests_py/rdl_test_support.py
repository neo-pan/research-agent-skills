import json
from pathlib import Path


def create_session(root: Path, session_id: str = "r1", mode: str = "research") -> Path:
    session_dir = root / ".rdl" / "sessions" / session_id
    round_dir = session_dir / "rounds" / "001"
    round_dir.mkdir(parents=True)

    state = {
        "schema_version": 1,
        "session_id": session_id,
        "mode": mode,
        "phase": "plan",
        "round": 1,
        "status": "active",
        "mission_file": "mission.md",
        "guard_session_id": None,
        "last_guard_command_id": None,
        "prompt_objective": "mission.md",
        "created_at_utc": "2026-06-29T00:00:00Z",
        "updated_at_utc": "2026-06-29T00:00:00Z",
    }
    write_json(session_dir / "state.json", state)
    write_json(session_dir / "integrity.json", {"entries": []})
    write_json(session_dir / "artifact-manifest.json", {"artifacts": []})

    (session_dir / "mission.md").write_text("# Mission\n\nFixture mission.\n", encoding="utf-8")
    (session_dir / "factors.md").write_text("# Factors\n\nFixture factors.\n", encoding="utf-8")
    (session_dir / "decision-ledger.md").write_text("# Decision Ledger\n", encoding="utf-8")
    (session_dir / "progress.md").write_text(COMPLETE_PROGRESS, encoding="utf-8")
    (round_dir / "prompt.md").write_text("# Prompt\n\nMode: fixture\n", encoding="utf-8")
    return session_dir


def complete_research_round(session_dir: Path, decision: str = "continue") -> None:
    round_dir = session_dir / "rounds" / "001"
    (round_dir / "evidence.md").write_text(COMPLETE_RESEARCH_EVIDENCE, encoding="utf-8")
    (round_dir / "interpretation.md").write_text(COMPLETE_INTERPRETATION, encoding="utf-8")
    (round_dir / "review.md").write_text(complete_review(decision), encoding="utf-8")
    (round_dir / "decision.md").write_text(complete_decision(decision, "claim"), encoding="utf-8")


def complete_build_round(session_dir: Path, verification: bool = True) -> None:
    round_dir = session_dir / "rounds" / "001"
    (round_dir / "intent.md").write_text(COMPLETE_INTENT, encoding="utf-8")
    (round_dir / "work.md").write_text(COMPLETE_WORK, encoding="utf-8")
    evidence = COMPLETE_BUILD_EVIDENCE if verification else INCOMPLETE_BUILD_EVIDENCE
    (round_dir / "evidence.md").write_text(evidence, encoding="utf-8")
    (round_dir / "review.md").write_text(complete_review("accept"), encoding="utf-8")
    (round_dir / "decision.md").write_text(complete_decision("accept", "capability"), encoding="utf-8")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def complete_review(decision: str) -> str:
    return f"""# Review

Reviewer: fixture
Review Mode: manual
Review Scope: current round
Artifacts Reviewed: prompt, evidence, decision
Verdict: PASS
Decision Reviewed: {decision}
Evidence Reviewed: fixture evidence
Blocking Evidence Gaps: none
Implementation Findings: none
Evaluation Integrity Findings: acceptable
Overclaim Risks: bounded
Readiness Level: ready
Recommended Decision: {decision}
"""


def complete_decision(decision: str, closes: str) -> str:
    return f"""# Decision

Decision: {decision}
Closes: {closes}
Evidence: fixture evidence
Uncertainty: bounded
What this rules out: unsupported alternatives
What remains unknown: later work
Recommended next loop: none
Next smallest step: continue same mode
"""


COMPLETE_PROGRESS = """# Progress

## Active

No active nonblocking items.

## Completed

No completed items yet.

## Blocked

No blocked items.

## Deferred

No deferred items.

## Open Questions

No open questions.
"""


COMPLETE_RESEARCH_EVIDENCE = """# Evidence

Research evidence: fixture claim evidence.

## Evaluation Integrity

Manual fixture integrity reviewed.

## Missing Evidence

No blocking missing evidence for this fixture.

## Evidence Budget

One local fixture check.
"""


COMPLETE_INTERPRETATION = """# Interpretation

Interpretation: fixture evidence supports the next research step.
"""


COMPLETE_INTENT = """# Intent

Intent: build the fixture capability.
"""


COMPLETE_WORK = """# Work

Work completed: fixture implementation change.
"""


COMPLETE_BUILD_EVIDENCE = """# Evidence

Verification evidence: fixture capability check passed.

## Evaluation Integrity

Manual fixture integrity reviewed.

## Missing Evidence

No blocking missing evidence for this fixture.

## Evidence Budget

One local fixture check.
"""


INCOMPLETE_BUILD_EVIDENCE = """# Evidence

Evidence exists but no verification is recorded.

## Evaluation Integrity

Manual fixture integrity reviewed.

## Missing Evidence

No blocking missing evidence for this fixture.

## Evidence Budget

One local fixture check.
"""

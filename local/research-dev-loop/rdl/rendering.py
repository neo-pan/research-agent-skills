"""Deterministic human and reviewer projections from normalized state."""

from __future__ import annotations

import json
from typing import Any

from .model import RdlError, current_round, digest


HANDOFF_SOFT_BYTES = 8 * 1024
HANDOFF_HARD_BYTES = 12 * 1024
REVIEW_HARD_BYTES = 30 * 1024


def render_views(state: dict[str, Any]) -> dict[str, str]:
    views = {
        "mission.md": _mission(state),
        "progress.md": _progress(state),
        "factors.md": _factors(state),
        "artifacts.json": json.dumps({"artifacts": state["artifacts"]}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "decision-ledger.md": _ledger(state),
    }
    for round_state in state["rounds"]:
        prefix = f"rounds/{round_state['number']:03d}"
        views[f"{prefix}/round.md"] = _round(state, round_state)
        if round_state["review_history"]:
            views[f"{prefix}/review.md"] = _review(round_state)
    if state["status"] != "active":
        views["final-report.md"] = _final_report(state)
    return views


def subject_projection(state: dict[str, Any], action: str, deterministic_findings: list[dict[str, Any]]) -> dict[str, Any]:
    round_state = current_round(state)
    evidence_ids = _relevant_evidence_ids(round_state)
    evidence = [item for item in state["evidence"] if item["id"] in evidence_ids]
    artifact_ids = {ref for item in evidence for ref in item["artifact_refs"]}
    decision = round_state.get("decision")
    if decision:
        artifact_ids.update(
            ref
            for evidence_id in decision["evidence_refs"]
            for ref in next((item["artifact_refs"] for item in evidence if item["id"] == evidence_id), [])
        )
    artifacts = [
        {
            "id": item["id"],
            "kind": item["kind"],
            "path": item["path"],
            "description": item["description"],
            "stability": item["stability"],
            "size_bytes": item["size_bytes"],
            "sha256": item["sha256"],
            **({"verifier": item["verifier"]} if "verifier" in item else {}),
        }
        for item in state["artifacts"]
        if item["id"] in artifact_ids
    ]
    return {
        "action": action,
        "mission": state["mission"],
        "mode": state["mode"],
        "progress": state["progress"],
        "factors": state["factors"],
        "round": {
            "number": round_state["number"],
            "mode": round_state["mode"],
            "evidence": evidence,
            "interpretation": round_state["interpretation"],
            "decision": round_state["decision"],
        },
        "artifacts": artifacts,
        "deterministic_findings": deterministic_findings,
    }


def subject_digest(state: dict[str, Any], action: str, deterministic_findings: list[dict[str, Any]]) -> str:
    return digest(subject_projection(state, action, deterministic_findings))


def review_pack(state: dict[str, Any], action: str, deterministic_findings: list[dict[str, Any]]) -> dict[str, Any]:
    projection = subject_projection(state, action, deterministic_findings)
    sections = {
        "mission": projection["mission"],
        "session": {"mode": projection["mode"], "progress": projection["progress"], "factors": projection["factors"]},
        "round": projection["round"],
        "artifacts": projection["artifacts"],
        "deterministic_findings": projection["deterministic_findings"],
    }
    pack = {
        "status": "ok",
        "session_id": state["session_id"],
        "action": action,
        "round": state["round"],
        "subject_digest": digest(projection),
        "reviewer_task": {
            "role": "fresh-context semantic reviewer",
            "questions": [
                "Does the evidence support the proposed decision without overclaim?",
                "Are counterevidence, confounders, staleness, and remaining uncertainty preserved?",
                "Is the proposed transition justified by the supplied subject?",
            ],
            "return": "action, subject_digest, adapter, verdict, and concise typed findings",
        },
        "finding_schema": {
            "severity": ["blocking", "warning", "note"],
            "disposition": "assigned later by the main agent when applying the result",
        },
        **sections,
    }
    _enforce_budget(pack, REVIEW_HARD_BYTES, "review_pack_over_budget", sections)
    return pack


def handoff(state: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    round_state = current_round(state)
    current_evidence = [item for item in state["evidence"] if item["id"] in _relevant_evidence_ids(round_state)]
    sections = {
        "mission": {"objective": state["mission"]["objective"], "scope": state["mission"]["scope"]},
        "progress": state["progress"],
        "factors": state["factors"],
        "round": {
            "number": state["round"],
            "mode": state["mode"],
            "evidence": [
                {key: item[key] for key in ("id", "claim", "summary", "bearing", "strength", "uncertainty")}
                for item in current_evidence
            ],
            "interpretation": round_state["interpretation"],
            "decision": round_state["decision"],
        },
        "readiness": readiness,
    }
    result = {
        "status": "ok",
        "session_id": state["session_id"],
        "state_version": state["state_version"],
        "session_status": state["status"],
        **sections,
        "warnings": [],
    }
    size = _encoded_size(result)
    if size > HANDOFF_HARD_BYTES:
        _over_budget("handoff_over_budget", HANDOFF_HARD_BYTES, sections, size)
    if size > HANDOFF_SOFT_BYTES:
        result["warnings"].append("handoff_soft_budget_exceeded")
    return result


def section_accounting(sections: dict[str, Any]) -> dict[str, int]:
    return {name: _encoded_size(value) for name, value in sections.items()}


def _enforce_budget(value: dict[str, Any], limit: int, code: str, sections: dict[str, Any]) -> None:
    size = _encoded_size(value)
    if size > limit:
        _over_budget(code, limit, sections, size)


def _over_budget(code: str, limit: int, sections: dict[str, Any], size: int) -> None:
    raise RdlError(
        code,
        f"projection is {size} bytes; hard limit is {limit}",
        status="blocked",
        details={"size_bytes": size, "limit_bytes": limit, "sections": section_accounting(sections)},
    )


def _encoded_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _mission(state: dict[str, Any]) -> str:
    mission = state["mission"]
    return (
        "# Mission\n\n"
        f"## Objective\n\n{mission['objective']}\n\n"
        f"## Scope\n\n{_bullets(mission['scope'])}\n"
        f"## Out of Scope\n\n{_bullets(mission['out_of_scope'])}\n"
        f"## Success Criteria\n\n{_bullets(mission['success_criteria'])}\n"
        f"## Invariants\n\n{_bullets(mission['invariants'])}\n"
        f"## Abort Criteria\n\n{_bullets(mission['abort_criteria'])}\n"
    )


def _progress(state: dict[str, Any]) -> str:
    lines = ["# Progress", ""]
    for key, entry in sorted(state["progress"].items()):
        lines.extend((f"## {key}", "", f"- Status: {entry['status']}", f"- Summary: {entry['summary']}", f"- Blocking: {'yes' if entry['blocking'] else 'no'}"))
        for field in ("reason", "required_input", "revisit_trigger"):
            if field in entry:
                lines.append(f"- {field.replace('_', ' ').title()}: {entry[field]}")
        if entry.get("evidence_refs"):
            lines.append(f"- Evidence: {', '.join(entry['evidence_refs'])}")
        lines.append("")
    if not state["progress"]:
        lines.extend(("No progress entries.", ""))
    return "\n".join(lines)


def _factors(state: dict[str, Any]) -> str:
    lines = ["# Factors", ""]
    for key, entry in sorted(state["factors"].items()):
        lines.extend((f"## {key}", "", f"- Category: {entry['category']}", f"- Value: {entry['value']}"))
        if "uncertainty" in entry:
            lines.append(f"- Uncertainty: {entry['uncertainty']}")
        lines.append("")
    if not state["factors"]:
        lines.extend(("No factors recorded.", ""))
    return "\n".join(lines)


def _round(state: dict[str, Any], round_state: dict[str, Any]) -> str:
    evidence_by_id = {item["id"]: item for item in state["evidence"]}
    event_by_id = {item["id"]: item for item in state["events"]}
    lines = [f"# Round {round_state['number']:03d}", "", f"Mode: {round_state['mode']}", "", "## Evidence", ""]
    for evidence_id in round_state["evidence_ids"]:
        item = evidence_by_id[evidence_id]
        lines.extend(
            (
                f"### {item['id']}: {item['claim']}",
                "",
                item["summary"],
                "",
                f"- Bearing: {item['bearing']}",
                f"- Strength: {item['strength']}",
                f"- Artifacts: {', '.join(item['artifact_refs']) or 'none'}",
                f"- Uncertainty: {item['uncertainty']}",
                "",
            )
        )
    if not round_state["evidence_ids"]:
        lines.extend(("No evidence recorded.", ""))
    interpretation = round_state["interpretation"]
    if interpretation:
        lines.extend(("## Interpretation", "", "### Shows", "", _bullets(interpretation["shows"]), "### Does Not Show", "", _bullets(interpretation["does_not_show"]), "### Uncertainty", "", _bullets(interpretation["uncertainty"]), "### Implications", "", _bullets(interpretation["implications"])))
    decision = round_state["decision"]
    if decision:
        lines.extend(("## Decision", "", f"- Kind: {decision['kind']}", f"- Subject: {decision['subject']}", f"- Evidence: {', '.join(decision['evidence_refs'])}", f"- Uncertainty: {decision['uncertainty']}", f"- Remaining unknowns: {'; '.join(decision['remaining_unknowns']) or 'none'}", f"- Next step: {decision['next_step']}", f"- Recommended transition: {decision['recommended_transition']}"))
        if "next_mode" in decision:
            lines.append(f"- Next mode: {decision['next_mode']}")
        if "close_outcome" in decision:
            lines.append(f"- Close outcome: {decision['close_outcome']}")
        lines.append("")
    if round_state["event_ids"]:
        lines.extend(("## Operational Events", ""))
        for event_id in round_state["event_ids"]:
            event = event_by_id[event_id]
            lines.append(f"- {event['id']} [{event['kind']}]: {event['summary']} (impact: {event['impact']})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _review(round_state: dict[str, Any]) -> str:
    lines = ["# Review", ""]
    for result in round_state["review_history"]:
        lines.extend((f"## {result['id']}", "", f"- Action: {result['action']}", f"- Subject Digest: {result['subject_digest']}", f"- Adapter: {result['adapter']}", f"- Verdict: {result['verdict']}", f"- Recorded Version: {result['recorded_version']}", ""))
        if result["findings"]:
            lines.extend(("### Findings", ""))
            for finding in result["findings"]:
                lines.append(f"- {finding['severity']} | {finding['category']} | {finding['claim']} | {finding['required_resolution']} | {finding['disposition']} | {finding['rationale']}")
            lines.append("")
    return "\n".join(lines)


def _ledger(state: dict[str, Any]) -> str:
    lines = ["# Decision Ledger", ""]
    for round_state in state["rounds"]:
        decision = round_state["decision"]
        if not decision:
            continue
        lines.extend((f"## Round {round_state['number']:03d}", "", f"- Kind: {decision['kind']}", f"- Subject: {decision['subject']}", f"- Transition: {decision['recommended_transition']}", f"- Evidence: {', '.join(decision['evidence_refs'])}", f"- Next step: {decision['next_step']}", ""))
    return "\n".join(lines)


def _final_report(state: dict[str, Any]) -> str:
    round_state = current_round(state)
    decision = round_state.get("decision")
    if state["status"] == "abandoned":
        reason = next((event["summary"] for event in reversed(state["events"]) if event["kind"] == "abandoned"), "not recorded")
        return f"# Final Report\n\n## Outcome\n\nabandoned\n\nScientific outcome claimed: none\n\n## Reason\n\n{reason}\n"
    outcome = state["status"].removeprefix("closed-")
    return (
        "# Final Report\n\n"
        f"## Outcome\n\n{outcome}\n\n"
        f"## Claim or Capability Closed\n\n{decision['subject'] if decision else 'not recorded'}\n\n"
        f"## Evidence Cited\n\n{_bullets(decision['evidence_refs'] if decision else [])}\n"
        f"## Uncertainty\n\n{decision['uncertainty'] if decision else 'not recorded'}\n\n"
        f"## Remaining Unknowns\n\n{_bullets(decision['remaining_unknowns'] if decision else [])}\n"
    )


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) + ("\n" if items else "None.\n")


def _relevant_evidence_ids(round_state: dict[str, Any]) -> set[str]:
    evidence_ids = set(round_state["evidence_ids"])
    decision = round_state.get("decision")
    if decision:
        evidence_ids.update(decision["evidence_refs"])
    return evidence_ids

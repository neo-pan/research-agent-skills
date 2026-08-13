"""Deterministic human and reviewer projections from normalized state."""

from __future__ import annotations

import json
from typing import Any

from .model import RdlError, current_round, digest


HANDOFF_SOFT_BYTES = 20 * 1024
HANDOFF_HARD_BYTES = 24 * 1024
REVIEW_SOFT_BYTES = 32 * 1024
REVIEW_HARD_BYTES = 48 * 1024
ARTIFACT_LIFECYCLE_GUIDANCE = (
    "Treat retired artifacts as historical rather than current decision-grade support. "
    "Check whether each superseding snapshot and verifier actually support the claim. "
    "Artifact drift establishes loss of the original binding; it does not by itself establish "
    "a negative scientific result. Require an inconclusive outcome or narrower claim unless "
    "independent evidence supports the stronger conclusion."
)
POST_NEXT_WRITE_THROUGH_GATE = (
    "Execute the instruction, freeze the smallest sufficient receipt or snapshot, then apply "
    "the current round's evidence, interpretation, and decision before any transition."
)


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
    artifact_ids = relevant_artifact_closure(state, round_state)
    artifacts = [_subject_artifact(item) for item in state["artifacts"] if item["id"] in artifact_ids]
    projection = {
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
    action_context = _review_action_context(state)
    if action_context is not None:
        projection["action_context"] = action_context
    return projection


def subject_digest(state: dict[str, Any], action: str, deterministic_findings: list[dict[str, Any]]) -> str:
    return digest(subject_projection(state, action, deterministic_findings))


def _review_pack(
    state: dict[str, Any], action: str, deterministic_findings: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    projection = subject_projection(state, action, deterministic_findings)
    evidence_coverage = _evidence_coverage(projection["round"])
    prior_review_context = _prior_review_context(current_round(state))
    sections = {
        "mission": projection["mission"],
        "session": {"mode": projection["mode"], "progress": projection["progress"], "factors": projection["factors"]},
        "action_context": projection.get("action_context"),
        "round": projection["round"],
        "artifacts": projection["artifacts"],
        "deterministic_findings": projection["deterministic_findings"],
        "evidence_coverage": evidence_coverage,
        "prior_review_context": prior_review_context,
    }
    if any("resolution" in item for item in projection["artifacts"]):
        sections["artifact_lifecycle_guidance"] = ARTIFACT_LIFECYCLE_GUIDANCE
    pack = {
        "status": "ok",
        "session_id": state["session_id"],
        "action": action,
        "round": state["round"],
        "subject_digest": digest(projection),
        "reviewer_task": {
            "role": "fresh-context semantic reviewer",
            "questions": _reviewer_questions(projection, action),
            "return": "action, subject_digest, adapter, verdict, and concise typed findings",
        },
        "finding_schema": {
            "severity": ["blocking", "warning", "note"],
            "category": "use success_criteria[i], a progress key, or a stable protocol category",
            "disposition": "assigned later by the main agent when applying the result",
        },
        **sections,
    }
    return pack, sections


def _review_action_context(state: dict[str, Any]) -> dict[str, Any] | None:
    if state["round"] <= 1:
        return None
    source_round = state["rounds"][state["round"] - 2]
    decision = source_round.get("decision")
    if not decision or decision.get("recommended_transition") != "next":
        return None
    return {
        "source_round": source_round["number"],
        "instruction": decision["next_step"],
        "decision_subject": decision["subject"],
    }


def _reviewer_questions(projection: dict[str, Any], action: str) -> list[str]:
    questions = [
        "Does the current evidence support the round decision without overclaim, including sufficient artifact or receipt bindings for decisive claims?",
        "Are counterevidence, confounders, staleness, and remaining uncertainty preserved?",
        "Are accepted prior findings resolved and rejected findings supported by retained rationale?",
    ]
    if action == "next":
        questions.extend(
            (
                "Does the supplied action_context, when present, have its checkable completion condition satisfied by this round?",
                "Are mission scope, out-of-scope boundaries, and invariants preserved?",
                "Is decision.next_step executable and does it retain all unfinished phases without hiding deferrals or unknowns?",
            )
        )
        return questions

    questions.extend(
        f"Is mission.success_criteria[{index}] evidence-backed within its stated scope: {criterion}"
        for index, criterion in enumerate(projection["mission"]["success_criteria"])
    )
    questions.extend(
        (
            "Is every active, blocked, deferred, or open-question progress entry reconciled with the proposed outcome?",
            "For a material build that closes a code, config, or script claim, is a current final-diff project-review receipt supplied and consistent with the claim?",
            "Is the positive, negative, or inconclusive outcome consistent with the decision, evidence, counterevidence, and remaining uncertainty?",
        )
    )
    return questions


def review_pack(
    state: dict[str, Any], action: str, deterministic_findings: list[dict[str, Any]]
) -> dict[str, Any]:
    pack, sections = _review_pack(state, action, deterministic_findings)
    _enforce_budget(pack, REVIEW_HARD_BYTES, "review_pack_over_budget", sections)
    return pack


def review_pack_diagnostics(
    state: dict[str, Any], action: str, deterministic_findings: list[dict[str, Any]]
) -> dict[str, Any]:
    pack, sections = _review_pack(state, action, deterministic_findings)
    size = _encoded_size(pack)
    return {
        "size_bytes": size,
        "soft_limit_bytes": REVIEW_SOFT_BYTES,
        "hard_limit_bytes": REVIEW_HARD_BYTES,
        "soft_limit_exceeded": size > REVIEW_SOFT_BYTES,
        "hard_limit_exceeded": size > REVIEW_HARD_BYTES,
        "sections": section_accounting(sections),
    }


def _evidence_coverage(round_projection: dict[str, Any]) -> list[dict[str, Any]]:
    decision = round_projection.get("decision")
    if not decision:
        return []
    evidence = {item["id"]: item for item in round_projection["evidence"]}
    return [
        {
            "evidence_id": evidence_id,
            "claim": evidence[evidence_id]["claim"],
            "artifact_refs": evidence[evidence_id]["artifact_refs"],
            "artifact_binding": "present" if evidence[evidence_id]["artifact_refs"] else "absent",
        }
        for evidence_id in decision["evidence_refs"]
    ]


def _prior_review_context(round_state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "review_id": item["id"],
            "action": item["action"],
            "subject_digest": item["subject_digest"],
            "verdict": item["verdict"],
            "recorded_version": item["recorded_version"],
            "findings": item["findings"],
        }
        for item in round_state["review_history"]
        if item["findings"]
    ]


def handoff(
    state: dict[str, Any], readiness: dict[str, Any], review_budget: dict[str, Any] | None = None
) -> dict[str, Any]:
    round_state = current_round(state)
    current_evidence = [item for item in state["evidence"] if item["id"] in _relevant_evidence_ids(round_state)]
    artifact_ids = relevant_artifact_closure(state, round_state)
    current_action, action_artifact_ids = _post_next_current_action(state)
    artifact_ids.update(action_artifact_ids)
    artifacts = []
    for item in state["artifacts"]:
        if item["id"] not in artifact_ids:
            continue
        artifact = {
            "id": item["id"],
            "kind": item["kind"],
            "path": item["path"],
            "stability": item["stability"],
            "integrity": {"size_bytes": item["size_bytes"], "sha256": item["sha256"]},
        }
        if "verifier" in item:
            artifact["verifier"] = item["verifier"]
        if "resolution" in item:
            artifact["resolution"] = item["resolution"]
        artifacts.append(artifact)
    decision = round_state["decision"]
    if state["status"] != "active" and decision is not None:
        decision = {key: value for key, value in decision.items() if key != "next_step"}
    sections = {
        "mission": state["mission"],
        "progress": state["progress"],
        "factors": state["factors"],
        "round": {
            "number": state["round"],
            "mode": state["mode"],
            "evidence": [
                {
                    key: item[key]
                    for key in ("id", "claim", "summary", "bearing", "strength", "artifact_refs", "uncertainty")
                }
                for item in current_evidence
            ],
            "interpretation": round_state["interpretation"],
            "decision": decision,
        },
        "artifacts": artifacts,
        "readiness": readiness,
    }
    terminal_summary = _terminal_summary(state)
    if terminal_summary is not None:
        sections["terminal_summary"] = terminal_summary
    if current_action is not None:
        sections["current_action"] = current_action
    if review_budget is not None:
        sections["review_budget"] = review_budget
    warnings = []
    if review_budget is not None:
        if review_budget["hard_limit_exceeded"]:
            warnings.append("review_pack_over_budget")
        elif review_budget["soft_limit_exceeded"]:
            warnings.append("review_pack_soft_budget_exceeded")
    result = {
        "status": "ok",
        "session_id": state["session_id"],
        "state_version": state["state_version"],
        "session_status": state["status"],
        **sections,
        "warnings": warnings,
    }
    full_size = _encoded_size(result)
    if full_size <= HANDOFF_HARD_BYTES:
        return result

    read_sections = ["/mission", "/progress", "/factors"]
    if current_action is not None:
        read_sections.append(f"/rounds/{state['round'] - 2}")
    read_sections.extend(
        (
            f"/rounds/{state['round'] - 1}",
            "/evidence",
            "/artifacts",
            "/events",
        )
    )
    omitted = ["mission", "progress", "factors", "round", "artifacts"]
    if current_action is not None:
        omitted.append("current_action")
    manifest = {
        "status": "ok",
        "session_id": state["session_id"],
        "state_version": state["state_version"],
        "session_status": state["status"],
        "projection_profile": "compact_manifest",
        "readiness": readiness,
        "canonical_state": {
            "path": (
                f".rdl/.store/{state['session_id']}/{state['state_version']}/state.json"
            ),
            "state_digest": state["state_digest"],
            "read_sections": read_sections,
        },
        "omitted_inline_sections": omitted,
        "warnings": ["handoff_full_inline_over_budget", *warnings],
        "accounting": {
            "full_inline_size_bytes": full_size,
            "inline_limit_bytes": HANDOFF_HARD_BYTES,
            "sections": section_accounting(sections),
        },
    }
    if review_budget is not None:
        manifest["review_budget"] = review_budget
    if state["status"] != "active":
        manifest["terminal_summary"] = _terminal_summary(state, compact=True)
        manifest["canonical_state"]["final_report_path"] = (
            f".rdl/.store/{state['session_id']}/{state['state_version']}/final-report.md"
        )
    manifest_size = _encoded_size(manifest)
    if manifest_size > HANDOFF_HARD_BYTES:
        _over_budget("handoff_over_budget", HANDOFF_HARD_BYTES, manifest, manifest_size)
    return manifest


def handoff_diagnostics(
    state: dict[str, Any], readiness: dict[str, Any], review_budget: dict[str, Any] | None = None
) -> dict[str, Any]:
    result = handoff(state, readiness, review_budget)
    profile = result.get("projection_profile", "full_inline")
    final_size = _encoded_size(result)
    if profile == "compact_manifest":
        full_size = result["accounting"]["full_inline_size_bytes"]
        sections = result["accounting"]["sections"]
    else:
        full_size = final_size
        sections = section_accounting(
            {
                key: result[key]
                for key in (
                    "mission",
                    "progress",
                    "factors",
                    "round",
                    "artifacts",
                    "readiness",
                    "review_budget",
                    "current_action",
                    "terminal_summary",
                )
                if key in result
            }
        )
    return {
        "profile": profile,
        "full_inline_size_bytes": full_size,
        "final_size_bytes": final_size,
        "optimization_target_exceeded": full_size > HANDOFF_SOFT_BYTES,
        "inline_limit_bytes": HANDOFF_HARD_BYTES,
        "sections": sections,
    }


def _post_next_current_action(state: dict[str, Any]) -> tuple[dict[str, Any] | None, set[str]]:
    if state["status"] != "active" or state["round"] <= 1 or current_round(state).get("decision") is not None:
        return None, set()
    source_round = state["rounds"][state["round"] - 2]
    decision = source_round.get("decision")
    if not decision or decision.get("recommended_transition") != "next":
        return None, set()
    evidence_ids = set(decision["evidence_refs"])
    evidence_by_id = {item["id"]: item for item in state["evidence"]}
    evidence = [
        {
            key: evidence_by_id[evidence_id][key]
            for key in ("id", "claim", "summary", "bearing", "strength", "artifact_refs", "uncertainty")
        }
        for evidence_id in decision["evidence_refs"]
    ]
    unfinished_progress = _unfinished_progress(state, compact=False)
    return (
        {
            "source_round": source_round["number"],
            "instruction": decision["next_step"],
            "decision_subject": decision["subject"],
            "evidence": evidence,
            "write_through_gate": POST_NEXT_WRITE_THROUGH_GATE,
            "remaining_protocol": {
                "success_criteria": state["mission"]["success_criteria"],
                "unfinished_progress": unfinished_progress,
            },
        },
        _artifact_closure_for_evidence_ids(state, evidence_ids),
    )


def _terminal_summary(state: dict[str, Any], *, compact: bool = False) -> dict[str, Any] | None:
    if state["status"] == "active":
        return None
    round_state = current_round(state)
    decision = round_state.get("decision")
    binding = round_state["latest_bindings"].get("close")
    unfinished_progress: list[dict[str, Any]] | dict[str, Any] = _unfinished_progress(state, compact=True)
    if compact:
        status_counts: dict[str, int] = {}
        for item in unfinished_progress:
            status = item["status"]
            status_counts[status] = status_counts.get(status, 0) + 1
        unfinished_progress = {
            "count": sum(status_counts.values()),
            "status_counts": status_counts,
            "read_section": "/progress",
        }
    historical_next_step = None
    if decision and decision.get("next_step"):
        historical_next_step = {"status": "pre_close_instruction"}
        if compact:
            historical_next_step["read_section"] = f"/rounds/{state['round'] - 1}/decision/next_step"
        else:
            historical_next_step["text"] = decision["next_step"]
    return {
        "outcome": state["status"].removeprefix("closed-"),
        "state_version": state["state_version"],
        "closed_at_utc": state["updated_at_utc"],
        "final_review_binding": (
            {
                "action": "close",
                "review_id": binding["review_id"],
                "subject_digest": binding["subject_digest"],
            }
            if state["status"].startswith("closed-") and binding is not None
            else None
        ),
        "unfinished_progress": unfinished_progress,
        "historical_next_step": historical_next_step,
    }


def _unfinished_progress(state: dict[str, Any], *, compact: bool) -> list[dict[str, Any]]:
    entries = []
    for key, entry in sorted(state["progress"].items()):
        if entry["status"] not in {"active", "blocked", "deferred", "open_question"}:
            continue
        if compact:
            entries.append({"key": key, "status": entry["status"], "blocking": entry["blocking"]})
        else:
            entries.append({"key": key, **entry})
    return entries


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
    summary = _terminal_summary(state)
    terminal_lines = [
        "## Terminal Summary",
        "",
        f"- State version: {summary['state_version']}",
        f"- Closed at: {summary['closed_at_utc']}",
        "- Final review: "
        + (
            f"{summary['final_review_binding']['review_id']} / {summary['final_review_binding']['subject_digest']}"
            if summary["final_review_binding"]
            else "none"
        ),
        "",
        "## Unfinished Progress",
        "",
        _bullets(
            [f"{item['key']}: {item['status']}" for item in summary["unfinished_progress"]]
        ).rstrip(),
        "",
        "## Historical Next Step",
        "",
        (
            f"pre_close_instruction: {summary['historical_next_step']['text']}"
            if summary["historical_next_step"]
            else "None."
        ),
        "",
    ]
    terminal_text = "\n".join(terminal_lines)
    if state["status"] == "abandoned":
        reason = next((event["summary"] for event in reversed(state["events"]) if event["kind"] == "abandoned"), "not recorded")
        return f"# Final Report\n\n## Outcome\n\nabandoned\n\nScientific outcome claimed: none\n\n## Reason\n\n{reason}\n\n{terminal_text}"
    outcome = state["status"].removeprefix("closed-")
    return (
        "# Final Report\n\n"
        f"## Outcome\n\n{outcome}\n\n"
        f"## Claim or Capability Closed\n\n{decision['subject'] if decision else 'not recorded'}\n\n"
        f"## Evidence Cited\n\n{_bullets(decision['evidence_refs'] if decision else [])}\n"
        f"## Uncertainty\n\n{decision['uncertainty'] if decision else 'not recorded'}\n\n"
        f"## Remaining Unknowns\n\n{_bullets(decision['remaining_unknowns'] if decision else [])}\n"
        f"{terminal_text}"
    )


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) + ("\n" if items else "None.\n")


def _relevant_evidence_ids(round_state: dict[str, Any]) -> set[str]:
    evidence_ids = set(round_state["evidence_ids"])
    decision = round_state.get("decision")
    if decision:
        evidence_ids.update(decision["evidence_refs"])
    return evidence_ids


def _subject_artifact(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "kind": item["kind"],
        "path": item["path"],
        "description": item["description"],
        "stability": item["stability"],
        "size_bytes": item["size_bytes"],
        "sha256": item["sha256"],
        **({"verifier": item["verifier"]} if "verifier" in item else {}),
        **({"resolution": item["resolution"]} if "resolution" in item else {}),
    }


def direct_relevant_artifact_ids(state: dict[str, Any], round_state: dict[str, Any]) -> set[str]:
    evidence_ids = _relevant_evidence_ids(round_state)
    return {
        ref
        for evidence in state["evidence"]
        if evidence["id"] in evidence_ids
        for ref in evidence["artifact_refs"]
    }


def relevant_artifact_closure(state: dict[str, Any], round_state: dict[str, Any]) -> set[str]:
    return _artifact_closure_for_evidence_ids(state, _relevant_evidence_ids(round_state))


def _artifact_closure_for_evidence_ids(state: dict[str, Any], evidence_ids: set[str]) -> set[str]:
    artifact_ids = {
        ref
        for evidence in state["evidence"]
        if evidence["id"] in evidence_ids
        for ref in evidence["artifact_refs"]
    }
    artifacts = {item["id"]: item for item in state["artifacts"]}
    pending = list(artifact_ids)
    while pending:
        artifact = artifacts.get(pending.pop())
        replacement_id = (artifact or {}).get("resolution", {}).get("replacement_artifact_id")
        if replacement_id and replacement_id not in artifact_ids:
            artifact_ids.add(replacement_id)
            pending.append(replacement_id)
    return artifact_ids

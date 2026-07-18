"""Normalized RDL state and request validation."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = 2
RISKS = frozenset({"routine", "material"})
MODES = frozenset({"research", "build"})
PROGRESS_STATUSES = frozenset(
    {"active", "completed", "blocked", "deferred", "open_question", "direction_tried"}
)
DECISION_KINDS = frozenset(
    {
        "continue",
        "accept",
        "reject",
        "pivot",
        "narrow",
        "broaden",
        "diagnose",
        "build",
        "profile",
        "rerun",
    }
)
MATERIAL_DECISIONS = frozenset({"accept", "reject", "pivot", "narrow", "broaden"})
TRANSITIONS = frozenset({"next", "close", "none"})
CLOSE_OUTCOMES = frozenset({"positive", "negative", "inconclusive", "abandoned"})
STABILITIES = frozenset({"snapshot", "live"})
BEARINGS = frozenset({"supports", "contradicts", "mixed", "context"})
STRENGTHS = frozenset({"strong", "moderate", "weak", "contradicted", "inconclusive"})
VERDICTS = frozenset({"pass", "pass_with_notes", "revise", "block", "inconclusive"})
SEVERITIES = frozenset({"blocking", "warning", "note"})
DISPOSITIONS = frozenset({"accepted", "rejected"})
KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True)
class RdlError(Exception):
    code: str
    message: str
    status: str = "error"
    details: dict[str, Any] = field(default_factory=dict)

    def result(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def state_digest(state: dict[str, Any]) -> str:
    semantic = deepcopy(state)
    semantic.pop("state_digest", None)
    return digest(semantic)


def request_digest(command: str, session_id: str, request: dict[str, Any]) -> str:
    return digest({"command": command, "session_id": session_id, "request": request})


def validate_session_id(value: str) -> str:
    if not KEY_RE.fullmatch(value) or value in {".", ".."}:
        raise RdlError("invalid_session_id", "session id must use letters, numbers, dot, underscore, or dash")
    return value


def validate_start(value: Any) -> dict[str, Any]:
    data = _object(value, "start request")
    _only(data, {"mode", "mission"}, "start request")
    mode = _enum(data.get("mode"), MODES, "mode")
    mission = _object(data.get("mission"), "mission")
    _only(
        mission,
        {"objective", "scope", "out_of_scope", "success_criteria", "invariants", "abort_criteria"},
        "mission",
    )
    normalized = {
        "objective": _text(mission.get("objective"), "mission.objective"),
        "scope": _text_list(mission.get("scope"), "mission.scope", required=True),
        "out_of_scope": _text_list(mission.get("out_of_scope", []), "mission.out_of_scope"),
        "success_criteria": _text_list(mission.get("success_criteria"), "mission.success_criteria", required=True),
        "invariants": _text_list(mission.get("invariants", []), "mission.invariants"),
        "abort_criteria": _text_list(mission.get("abort_criteria", []), "mission.abort_criteria"),
    }
    return {"mode": mode, "mission": normalized}


def validate_delta(value: Any) -> dict[str, Any]:
    data = _object(value, "ApplyDelta")
    allowed = {
        "expected_state_version",
        "risk",
        "artifacts",
        "evidence",
        "events",
        "progress_updates",
        "factor_updates",
        "interpretation",
        "decision",
        "review_trigger",
        "review_result",
    }
    _only(data, allowed, "ApplyDelta")
    version = _positive_int(data.get("expected_state_version"), "expected_state_version")
    risk = _enum(data.get("risk"), RISKS, "risk")
    normalized: dict[str, Any] = {"expected_state_version": version, "risk": risk}
    normalized["artifacts"] = _map(data.get("artifacts", {}), "artifacts", _artifact)
    normalized["evidence"] = _map(data.get("evidence", {}), "evidence", _evidence)
    normalized["events"] = _map(data.get("events", {}), "events", _event)
    normalized["progress_updates"] = _map(
        data.get("progress_updates", {}), "progress_updates", _progress, allow_null=True
    )
    normalized["factor_updates"] = _map(
        data.get("factor_updates", {}), "factor_updates", _factor, allow_null=True
    )
    if "interpretation" in data:
        if data["interpretation"] is None:
            raise RdlError("invalid_null", "interpretation cannot be null")
        normalized["interpretation"] = _interpretation(data["interpretation"], "interpretation")
    if "decision" in data:
        if data["decision"] is None:
            raise RdlError("invalid_null", "decision cannot be null")
        normalized["decision"] = _decision(data["decision"], "decision")
    if "review_trigger" in data:
        if data["review_trigger"] is None:
            raise RdlError("invalid_null", "review_trigger cannot be null")
        normalized["review_trigger"] = _review_trigger(data["review_trigger"], "review_trigger")
    if "review_result" in data:
        if data["review_result"] is None:
            raise RdlError("invalid_null", "review_result cannot be null")
        normalized["review_result"] = _review_result(data["review_result"], "review_result")
    return normalized


def new_state(session_id: str, start: dict[str, Any], start_request_digest: str) -> dict[str, Any]:
    now = now_utc()
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "state_version": 1,
        "mode": start["mode"],
        "status": "active",
        "round": 1,
        "mission": deepcopy(start["mission"]),
        "progress": {},
        "factors": {},
        "artifacts": [],
        "evidence": [],
        "events": [],
        "rounds": [_new_round(1, start["mode"])],
        "counters": {"artifact": 0, "evidence": 0, "event": 0, "review": 0},
        "created_at_utc": now,
        "updated_at_utc": now,
        "start_replay": {"request_digest": start_request_digest, "receipt": None},
        "last_mutation": None,
    }
    return state


def new_round(number: int, mode: str) -> dict[str, Any]:
    return _new_round(number, mode)


def validate_loaded_state(state: Any, session_id: str) -> dict[str, Any]:
    data = _object(state, "state.json")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise RdlError("unsupported_schema", f"state schema must be {SCHEMA_VERSION}")
    if data.get("session_id") != session_id:
        raise RdlError("session_identity_mismatch", "state session id does not match its store location")
    expected = data.get("state_digest")
    if not isinstance(expected, str) or expected != state_digest(data):
        raise RdlError("state_digest_mismatch", "state.json digest is missing or invalid")
    return data


def semantic_delta_present(delta: dict[str, Any]) -> bool:
    return any(
        (
            delta.get("artifacts"),
            delta.get("evidence"),
            delta.get("events"),
            delta.get("progress_updates"),
            delta.get("factor_updates"),
            "interpretation" in delta,
            "decision" in delta,
            "review_trigger" in delta,
        )
    )


def current_round(state: dict[str, Any]) -> dict[str, Any]:
    return state["rounds"][state["round"] - 1]


def _new_round(number: int, mode: str) -> dict[str, Any]:
    return {
        "number": number,
        "mode": mode,
        "evidence_ids": [],
        "event_ids": [],
        "interpretation": None,
        "decision": None,
        "material_required": False,
        "review_history": [],
        "latest_bindings": {},
        "evidence_free_corrections": 0,
    }


def _artifact(value: Any, field_name: str) -> dict[str, Any]:
    data = _object(value, field_name)
    _only(data, {"kind", "path", "description", "stability", "verifier"}, field_name)
    result = {
        "kind": _text(data.get("kind"), f"{field_name}.kind"),
        "path": _relative_path(data.get("path"), f"{field_name}.path"),
        "description": _text(data.get("description"), f"{field_name}.description"),
        "stability": _enum(data.get("stability", "snapshot"), STABILITIES, f"{field_name}.stability"),
    }
    if "verifier" in data:
        verifier = _object(data["verifier"], f"{field_name}.verifier")
        _only(verifier, {"name", "status", "summary"}, f"{field_name}.verifier")
        result["verifier"] = {
            "name": _text(verifier.get("name"), f"{field_name}.verifier.name"),
            "status": _text(verifier.get("status"), f"{field_name}.verifier.status"),
            "summary": _text(verifier.get("summary"), f"{field_name}.verifier.summary"),
        }
    return result


def _evidence(value: Any, field_name: str) -> dict[str, Any]:
    data = _object(value, field_name)
    _only(data, {"claim", "summary", "bearing", "strength", "artifact_refs", "uncertainty"}, field_name)
    return {
        "claim": _text(data.get("claim"), f"{field_name}.claim"),
        "summary": _text(data.get("summary"), f"{field_name}.summary"),
        "bearing": _enum(data.get("bearing"), BEARINGS, f"{field_name}.bearing"),
        "strength": _enum(data.get("strength"), STRENGTHS, f"{field_name}.strength"),
        "artifact_refs": _ref_list(data.get("artifact_refs", []), f"{field_name}.artifact_refs"),
        "uncertainty": _text(data.get("uncertainty", "none recorded"), f"{field_name}.uncertainty"),
    }


def _event(value: Any, field_name: str) -> dict[str, Any]:
    data = _object(value, field_name)
    _only(data, {"kind", "summary", "impact"}, field_name)
    return {
        "kind": _text(data.get("kind"), f"{field_name}.kind"),
        "summary": _text(data.get("summary"), f"{field_name}.summary"),
        "impact": _text(data.get("impact", "none"), f"{field_name}.impact"),
    }


def _progress(value: Any, field_name: str) -> dict[str, Any]:
    data = _object(value, field_name)
    _only(
        data,
        {"status", "summary", "blocking", "reason", "required_input", "revisit_trigger", "evidence_refs"},
        field_name,
    )
    result: dict[str, Any] = {
        "status": _enum(data.get("status"), PROGRESS_STATUSES, f"{field_name}.status"),
        "summary": _text(data.get("summary"), f"{field_name}.summary"),
        "blocking": _boolean(data.get("blocking", False), f"{field_name}.blocking"),
    }
    for key in ("reason", "required_input", "revisit_trigger"):
        if key in data:
            result[key] = _text(data[key], f"{field_name}.{key}")
    if "evidence_refs" in data:
        result["evidence_refs"] = _ref_list(data["evidence_refs"], f"{field_name}.evidence_refs")
    return result


def _factor(value: Any, field_name: str) -> dict[str, Any]:
    data = _object(value, field_name)
    _only(data, {"category", "value", "uncertainty"}, field_name)
    result = {
        "category": _text(data.get("category"), f"{field_name}.category"),
        "value": _text(data.get("value"), f"{field_name}.value"),
    }
    if "uncertainty" in data:
        result["uncertainty"] = _text(data["uncertainty"], f"{field_name}.uncertainty")
    return result


def _interpretation(value: Any, field_name: str) -> dict[str, Any]:
    data = _object(value, field_name)
    _only(data, {"shows", "does_not_show", "uncertainty", "implications"}, field_name)
    return {
        "shows": _text_list(data.get("shows"), f"{field_name}.shows", required=True),
        "does_not_show": _text_list(data.get("does_not_show", []), f"{field_name}.does_not_show"),
        "uncertainty": _text_list(data.get("uncertainty"), f"{field_name}.uncertainty", required=True),
        "implications": _text_list(data.get("implications", []), f"{field_name}.implications"),
    }


def _decision(value: Any, field_name: str) -> dict[str, Any]:
    data = _object(value, field_name)
    _only(
        data,
        {
            "kind",
            "subject",
            "evidence_refs",
            "uncertainty",
            "remaining_unknowns",
            "next_step",
            "next_mode",
            "recommended_transition",
            "close_outcome",
        },
        field_name,
    )
    transition = _enum(data.get("recommended_transition"), TRANSITIONS, f"{field_name}.recommended_transition")
    result: dict[str, Any] = {
        "kind": _enum(data.get("kind"), DECISION_KINDS, f"{field_name}.kind"),
        "subject": _text(data.get("subject"), f"{field_name}.subject"),
        "evidence_refs": _ref_list(data.get("evidence_refs"), f"{field_name}.evidence_refs", required=True),
        "uncertainty": _text(data.get("uncertainty"), f"{field_name}.uncertainty"),
        "remaining_unknowns": _text_list(
            data.get("remaining_unknowns", []), f"{field_name}.remaining_unknowns"
        ),
        "next_step": _text(data.get("next_step"), f"{field_name}.next_step"),
        "recommended_transition": transition,
    }
    if "next_mode" in data:
        result["next_mode"] = _enum(data["next_mode"], MODES, f"{field_name}.next_mode")
    if transition == "close":
        result["close_outcome"] = _enum(
            data.get("close_outcome"), CLOSE_OUTCOMES - {"abandoned"}, f"{field_name}.close_outcome"
        )
    elif "close_outcome" in data:
        raise RdlError("invalid_decision", "close_outcome is only valid for a close decision")
    return result


def _review_trigger(value: Any, field_name: str) -> dict[str, Any]:
    data = _object(value, field_name)
    _only(data, {"code", "reason"}, field_name)
    return {
        "code": _text(data.get("code"), f"{field_name}.code"),
        "reason": _text(data.get("reason"), f"{field_name}.reason"),
    }


def _review_result(value: Any, field_name: str) -> dict[str, Any]:
    data = _object(value, field_name)
    _only(data, {"action", "subject_digest", "adapter", "verdict", "findings"}, field_name)
    action = _enum(data.get("action"), {"next", "close"}, f"{field_name}.action")
    subject = _text(data.get("subject_digest"), f"{field_name}.subject_digest")
    if not re.fullmatch(r"[0-9a-f]{64}", subject):
        raise RdlError("invalid_subject_digest", "review_result.subject_digest must be a sha256 hex digest")
    findings_value = data.get("findings", [])
    if not isinstance(findings_value, list):
        raise RdlError("invalid_type", f"{field_name}.findings must be an array")
    findings = [_finding(item, f"{field_name}.findings[{index}]") for index, item in enumerate(findings_value)]
    return {
        "action": action,
        "subject_digest": subject,
        "adapter": _text(data.get("adapter"), f"{field_name}.adapter"),
        "verdict": _enum(data.get("verdict"), VERDICTS, f"{field_name}.verdict"),
        "findings": findings,
    }


def _finding(value: Any, field_name: str) -> dict[str, Any]:
    data = _object(value, field_name)
    _only(
        data,
        {"severity", "category", "claim", "required_resolution", "disposition", "rationale"},
        field_name,
    )
    return {
        "severity": _enum(data.get("severity"), SEVERITIES, f"{field_name}.severity"),
        "category": _text(data.get("category"), f"{field_name}.category"),
        "claim": _text(data.get("claim"), f"{field_name}.claim"),
        "required_resolution": _text(data.get("required_resolution"), f"{field_name}.required_resolution"),
        "disposition": _enum(data.get("disposition"), DISPOSITIONS, f"{field_name}.disposition"),
        "rationale": _text(data.get("rationale"), f"{field_name}.rationale"),
    }


def _map(value: Any, name: str, validator, *, allow_null: bool = False) -> dict[str, Any]:
    data = _object(value, name)
    result: dict[str, Any] = {}
    for key, item in data.items():
        if not isinstance(key, str) or not KEY_RE.fullmatch(key):
            raise RdlError("invalid_key", f"{name} keys must be stable identifiers")
        if item is None:
            if not allow_null:
                raise RdlError("invalid_null", f"{name}.{key} cannot be null")
            result[key] = None
        else:
            result[key] = validator(item, f"{name}.{key}")
    return result


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RdlError("invalid_type", f"{name} must be an object")
    return value


def _only(data: dict[str, Any], allowed: set[str], name: str) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise RdlError("unknown_field", f"{name} has unknown fields", details={"fields": extra})


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RdlError("invalid_text", f"{name} must be a non-empty string")
    return value.strip()


def _text_list(value: Any, name: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise RdlError("invalid_type", f"{name} must be an array")
    result = [_text(item, f"{name}[{index}]") for index, item in enumerate(value)]
    if required and not result:
        raise RdlError("missing_items", f"{name} must not be empty")
    return result


def _ref_list(value: Any, name: str, *, required: bool = False) -> list[str]:
    result = _text_list(value, name, required=required)
    for ref in result:
        if not KEY_RE.fullmatch(ref):
            raise RdlError("invalid_reference", f"{name} contains an invalid reference: {ref}")
    return result


def _enum(value: Any, allowed: set[str] | frozenset[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise RdlError("invalid_value", f"{name} must be one of: {', '.join(sorted(allowed))}")
    return value


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RdlError("invalid_version", f"{name} must be a positive integer")
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise RdlError("invalid_type", f"{name} must be a boolean")
    return value


def _relative_path(value: Any, name: str) -> str:
    text = _text(value, name)
    if text.startswith("/") or any(part == ".." for part in text.split("/")):
        raise RdlError("invalid_artifact_path", f"{name} must be a project-relative path")
    return text

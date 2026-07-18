"""Deep RDL command module."""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import rendering
from .model import (
    CLOSE_OUTCOMES,
    MATERIAL_DECISIONS,
    RdlError,
    current_round,
    new_round,
    new_state,
    now_utc,
    request_digest,
    state_digest,
    validate_delta,
    validate_session_id,
    validate_start,
)
from .store import Repository


class EvaluationContext:
    def __init__(self, root: Path):
        self.root = root
        self.cache: dict[str, dict[str, Any] | RdlError] = {}
        self.read_counts: dict[str, int] = {}

    def inspect(self, relative: str) -> dict[str, Any]:
        path = (self.root / relative).resolve()
        try:
            key = path.relative_to(self.root).as_posix()
        except ValueError as exc:
            raise RdlError("artifact_path_escape", f"artifact escapes project root: {relative}") from exc
        if key in self.cache:
            cached = self.cache[key]
            if isinstance(cached, RdlError):
                raise cached
            return cached
        self.read_counts[key] = self.read_counts.get(key, 0) + 1
        try:
            hasher = hashlib.sha256()
            size = 0
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    size += len(chunk)
                    hasher.update(chunk)
        except FileNotFoundError as exc:
            error = RdlError(
                "artifact_missing", f"artifact does not exist: {relative}", status="blocked", details={"path": relative}
            )
            self.cache[key] = error
            raise error from exc
        except OSError as exc:
            error = RdlError(
                "artifact_unreadable", f"artifact cannot be read: {relative}", status="blocked", details={"path": relative}
            )
            self.cache[key] = error
            raise error from exc
        result = {"size_bytes": size, "sha256": hasher.hexdigest()}
        self.cache[key] = result
        return result


class RdlEngine:
    """Execute every RDL command through one state and transaction seam."""

    def __init__(self, root: str | Path, repository: Repository | None = None):
        self.root = Path(root).resolve()
        self.repository = repository or Repository(self.root)

    def execute(
        self,
        command: str,
        *,
        session_id: str | None = None,
        request: dict[str, Any] | None = None,
        action: str | None = None,
        expected_state_version: int | None = None,
        outcome: str | None = None,
        reason: str | None = None,
        diagnostics: bool = False,
    ) -> dict[str, Any]:
        if command == "start":
            return self._start(session_id, request)
        selected = self.repository.select_session_id(session_id)
        with self.repository.session_lock(selected):
            state = self.repository.load(selected)
            if command == "handoff":
                return self._handoff(state)
            if command == "doctor":
                return self._doctor(state, diagnostics)
            if command == "review":
                return self._review(state, action)
            if command == "apply":
                return self._apply(state, request)
            if command == "next":
                return self._next(state, expected_state_version)
            if command == "close":
                return self._close(state, expected_state_version, outcome, reason)
        raise RdlError("unknown_command", f"unknown command: {command}")

    def _start(self, requested_id: str | None, raw: dict[str, Any] | None) -> dict[str, Any]:
        start = validate_start(raw)
        explicit = requested_id is not None
        session_id = validate_session_id(requested_id) if explicit else self._generated_session_id()
        digest_value = request_digest("start", session_id, start)
        with self.repository.start_lock():
            pointer = self.repository.pointer(session_id)
            if pointer.is_symlink():
                if not explicit:
                    raise RdlError("session_already_exists", f"session already exists: {session_id}", status="blocked")
                with self.repository.session_lock(session_id):
                    existing = self.repository.load(session_id)
                    replay = existing.get("start_replay") or {}
                    if replay.get("request_digest") == digest_value and isinstance(replay.get("receipt"), dict):
                        return deepcopy(replay["receipt"])
                raise RdlError("session_already_exists", f"session already exists: {session_id}", status="blocked")
            active = self.repository.active_session_ids()
            if active:
                raise RdlError(
                    "active_session_exists",
                    "an active RDL session already exists",
                    status="blocked",
                    details={"session_id": active[0]},
                )
            self.repository.discard_uncommitted_start(session_id)
            state = new_state(session_id, start, digest_value)
            receipt = {
                "status": "ok",
                "session_id": session_id,
                "round": 1,
                "state_version": 1,
                "assigned_ids": {},
                "effective_risk": "routine",
                "review_required": False,
                "transition_readiness": "needs_evidence",
                "warnings": [],
            }
            state["start_replay"]["receipt"] = deepcopy(receipt)
            state["state_digest"] = state_digest(state)
            self.repository.commit(session_id, state, rendering.render_views(state))
            return receipt

    def _apply(self, state: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
        delta = validate_delta(raw)
        command_digest = request_digest("apply", state["session_id"], delta)
        replay = self._replay_or_check_version(state, delta["expected_state_version"], command_digest)
        if replay is not None:
            return replay
        self._require_active(state)
        self.repository.cleanup(state["session_id"], state["state_version"])
        before = deepcopy(state)
        before_round = current_round(before)
        review_result = delta.get("review_result")
        previous_subject = None
        context = EvaluationContext(self.root)
        if review_result:
            deterministic = self._deterministic_findings(before, context)
            previous_subject = rendering.subject_digest(before, review_result["action"], deterministic)
            if review_result["subject_digest"] != previous_subject:
                raise RdlError(
                    "stale_review_result",
                    "review result does not match the current action and subject",
                    status="blocked",
                    details={"expected_subject_digest": previous_subject},
                )
            if any(
                item["action"] == review_result["action"] and item["subject_digest"] == previous_subject
                for item in before_round["review_history"]
            ):
                raise RdlError("duplicate_review", "the same action and subject digest was already reviewed", status="blocked")

        updated = deepcopy(state)
        round_state = current_round(updated)
        assigned: dict[str, dict[str, str]] = {}
        artifact_ids = self._apply_artifacts(updated, delta["artifacts"], context, assigned)
        evidence_ids = self._apply_evidence(updated, delta["evidence"], artifact_ids, assigned)
        self._apply_events(updated, delta["events"], assigned)
        self._apply_progress(updated, delta["progress_updates"], evidence_ids)
        self._apply_factors(updated, delta["factor_updates"])
        if "interpretation" in delta:
            round_state["interpretation"] = deepcopy(delta["interpretation"])
        if "decision" in delta:
            decision = deepcopy(delta["decision"])
            decision["evidence_refs"] = self._resolve_refs(
                decision["evidence_refs"], evidence_ids, {item["id"] for item in updated["evidence"]}, "evidence"
            )
            round_state["decision"] = decision
        if "review_trigger" in delta:
            round_state["review_trigger"] = deepcopy(delta["review_trigger"])

        target_version = state["state_version"] + 1
        if review_result:
            review_id = self._next_id(updated, "review", "R")
            record = deepcopy(review_result)
            record.update({"id": review_id, "recorded_version": target_version})
            round_state["review_history"].append(record)
            round_state["latest_bindings"][record["action"]] = {
                "review_id": review_id,
                "subject_digest": record["subject_digest"],
            }
            assigned.setdefault("reviews", {})["result"] = review_id

        reasons: list[str] = []
        if "decision" in delta and delta["decision"]["kind"] in MATERIAL_DECISIONS:
            reasons.append(f"decision:{delta['decision']['kind']}")
        if "decision" in delta and delta["decision"]["recommended_transition"] == "close":
            reasons.append(f"scientific_close:{delta['decision']['close_outcome']}")
        if "review_trigger" in delta:
            reasons.append(f"review_trigger:{delta['review_trigger']['code']}")
        effective_risk = "material" if delta["risk"] == "material" or reasons else "routine"
        if effective_risk == "material":
            round_state["material_required"] = True

        deterministic = self._deterministic_findings(updated, context)
        transition_action = self._transition_action(updated)
        current_subject = (
            rendering.subject_digest(updated, transition_action, deterministic) if transition_action in {"next", "close"} else None
        )
        if review_result and previous_subject != current_subject:
            if delta["evidence"]:
                round_state["evidence_free_corrections"] = 0
            else:
                if before_round["evidence_free_corrections"] >= 1:
                    raise RdlError(
                        "review_correction_limit",
                        "a second evidence-free subject correction is not allowed",
                        status="blocked",
                    )
                round_state["evidence_free_corrections"] = before_round["evidence_free_corrections"] + 1
        elif delta["evidence"]:
            round_state["evidence_free_corrections"] = 0

        updated["state_version"] = target_version
        updated["updated_at_utc"] = now_utc()
        readiness = self._readiness(
            updated,
            transition_action,
            context=context,
            deterministic_findings=deterministic,
        )
        receipt: dict[str, Any] = {
            "status": "ok",
            "session_id": updated["session_id"],
            "round": updated["round"],
            "state_version": target_version,
            "assigned_ids": assigned,
            "effective_risk": effective_risk,
            "review_required": readiness["status"] == "needs_review",
            "transition_readiness": readiness["status"],
            "warnings": readiness["warnings"],
        }
        if reasons and delta["risk"] == "routine":
            receipt["risk_upgrade_reasons"] = reasons
        if current_subject is not None and readiness["status"] == "needs_review":
            receipt["review_subject_digest"] = current_subject
        updated["last_mutation"] = {
            "base_version": state["state_version"],
            "request_digest": command_digest,
            "receipt": deepcopy(receipt),
        }
        updated["state_digest"] = state_digest(updated)
        self.repository.commit(updated["session_id"], updated, rendering.render_views(updated))
        return receipt

    def _next(self, state: dict[str, Any], expected: int | None) -> dict[str, Any]:
        request = {"expected_state_version": self._expected(expected)}
        command_digest = request_digest("next", state["session_id"], request)
        replay = self._replay_or_check_version(state, request["expected_state_version"], command_digest)
        if replay is not None:
            return replay
        self._require_active(state)
        self.repository.cleanup(state["session_id"], state["state_version"])
        context = EvaluationContext(self.root)
        readiness = self._readiness(state, "next", context=context)
        if readiness["status"] != "ready":
            raise RdlError("transition_not_ready", "current round is not ready for next", status="blocked", details=readiness)
        updated = deepcopy(state)
        decision = current_round(updated)["decision"]
        next_mode = decision.get("next_mode", updated["mode"])
        updated["round"] += 1
        updated["mode"] = next_mode
        updated["rounds"].append(new_round(updated["round"], next_mode))
        return self._commit_transition(updated, state, "next", request, command_digest, "needs_evidence")

    def _close(self, state: dict[str, Any], expected: int | None, outcome: str | None, reason: str | None) -> dict[str, Any]:
        version = self._expected(expected)
        if outcome not in CLOSE_OUTCOMES:
            raise RdlError("invalid_close_outcome", "close outcome must be positive, negative, inconclusive, or abandoned")
        request: dict[str, Any] = {"expected_state_version": version, "outcome": outcome}
        if reason is not None:
            request["reason"] = reason.strip()
        if outcome == "abandoned" and not request.get("reason"):
            raise RdlError("missing_abandon_reason", "abandoned close requires --reason")
        if outcome != "abandoned" and reason is not None:
            raise RdlError("unexpected_close_reason", "--reason is only valid for abandoned close")
        command_digest = request_digest("close", state["session_id"], request)
        replay = self._replay_or_check_version(state, version, command_digest)
        if replay is not None:
            return replay
        self._require_active(state)
        self.repository.cleanup(state["session_id"], state["state_version"])
        updated = deepcopy(state)
        if outcome == "abandoned":
            event_id = self._next_id(updated, "event", "EV")
            updated["events"].append(
                {
                    "id": event_id,
                    "round": updated["round"],
                    "kind": "abandoned",
                    "summary": request["reason"],
                    "impact": "scientific outcome claimed: none",
                }
            )
            current_round(updated)["event_ids"].append(event_id)
            updated["status"] = "abandoned"
        else:
            decision = current_round(state).get("decision")
            if not decision or decision.get("recommended_transition") != "close" or decision.get("close_outcome") != outcome:
                raise RdlError("close_decision_mismatch", "close outcome does not match the current decision", status="blocked")
            readiness = self._readiness(state, "close", context=EvaluationContext(self.root))
            if readiness["status"] != "ready":
                raise RdlError("transition_not_ready", "current round is not ready to close", status="blocked", details=readiness)
            updated["status"] = f"closed-{outcome}"
        return self._commit_transition(updated, state, "close", request, command_digest, "terminal")

    def _commit_transition(
        self,
        updated: dict[str, Any],
        previous: dict[str, Any],
        command: str,
        request: dict[str, Any],
        command_digest: str,
        readiness: str,
    ) -> dict[str, Any]:
        updated["state_version"] = previous["state_version"] + 1
        updated["updated_at_utc"] = now_utc()
        receipt = {
            "status": "ok",
            "session_id": updated["session_id"],
            "round": updated["round"],
            "state_version": updated["state_version"],
            "assigned_ids": {},
            "effective_risk": "material" if command == "close" and updated["status"] != "abandoned" else "routine",
            "review_required": False,
            "transition_readiness": readiness,
            "warnings": [],
        }
        updated["last_mutation"] = {
            "base_version": previous["state_version"],
            "request_digest": command_digest,
            "receipt": deepcopy(receipt),
        }
        updated["state_digest"] = state_digest(updated)
        self.repository.commit(updated["session_id"], updated, rendering.render_views(updated))
        return receipt

    def _handoff(self, state: dict[str, Any]) -> dict[str, Any]:
        readiness = self._readiness(state, self._transition_action(state), context=EvaluationContext(self.root))
        return rendering.handoff(state, readiness)

    def _review(self, state: dict[str, Any], action: str | None) -> dict[str, Any]:
        if action not in {"next", "close"}:
            raise RdlError("invalid_review_action", "review action must be next or close")
        if self._transition_action(state) != action:
            raise RdlError("review_action_mismatch", "review action does not match the current decision", status="blocked")
        context = EvaluationContext(self.root)
        findings = self._deterministic_findings(state, context)
        readiness = self._readiness(state, action, context=context, deterministic_findings=findings)
        if readiness["status"] != "needs_review":
            raise RdlError(
                "review_not_required",
                "the current subject does not require review",
                status="blocked",
                details=readiness,
            )
        return rendering.review_pack(state, action, findings)

    def _doctor(self, state: dict[str, Any], diagnostics: bool) -> dict[str, Any]:
        context = EvaluationContext(self.root)
        findings = self._deterministic_findings(state, context)
        expected_views = {key: value.encode("utf-8") for key, value in rendering.render_views(state).items()}
        actual_views = self.repository.read_views(state["session_id"])
        if actual_views != expected_views:
            findings.append({"code": "derived_view_drift", "severity": "warning", "message": "derived views differ from state.json"})
        generation = self.repository.generation_diagnostics(state["session_id"], state["state_version"])
        if generation["temporary"] or generation["unreferenced"]:
            findings.append({"code": "orphan_generations", "severity": "warning", "message": "temporary or unreferenced generations exist"})
        result: dict[str, Any] = {
            "status": "blocked" if any(item["severity"] == "blocking" for item in findings) else "ok",
            "session_id": state["session_id"],
            "state_version": state["state_version"],
            "session_status": state["status"],
            "findings": findings,
        }
        if diagnostics:
            result["diagnostics"] = {"artifact_read_counts": context.read_counts, "generations": generation}
        return result

    def _readiness(
        self,
        state: dict[str, Any],
        action: str | None,
        *,
        context: EvaluationContext,
        deterministic_findings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if state["status"] != "active":
            return {"status": "terminal", "blockers": [], "warnings": []}
        if action not in {"next", "close"}:
            return {"status": "needs_evidence", "blockers": ["missing_transition_decision"], "warnings": []}
        round_state = current_round(state)
        findings = deterministic_findings
        if findings is None:
            findings = self._deterministic_findings(state, context)
        blockers = [item["code"] for item in findings if item["severity"] == "blocking"]
        decision = round_state.get("decision")
        if not decision:
            blockers.append("missing_decision")
        elif decision.get("recommended_transition") != action:
            blockers.append("decision_transition_mismatch")
        if not round_state["evidence_ids"]:
            blockers.append("missing_evidence")
        if round_state["material_required"]:
            digest_value = rendering.subject_digest(state, action, findings)
            binding = round_state["latest_bindings"].get(action)
            if not binding or binding.get("subject_digest") != digest_value:
                blockers.append("missing_fresh_review")
            else:
                review = next((item for item in round_state["review_history"] if item["id"] == binding["review_id"]), None)
                if not review or review["verdict"] not in {"pass", "pass_with_notes"}:
                    blockers.append("review_not_passing")
                elif any(
                    finding["severity"] == "blocking" and finding["disposition"] == "accepted"
                    for finding in review["findings"]
                ):
                    blockers.append("accepted_blocking_review_finding")
        blocker_set = set(blockers)
        return {
            "status": "ready" if not blockers else ("needs_review" if blocker_set == {"missing_fresh_review"} else "blocked"),
            "blockers": list(dict.fromkeys(blockers)),
            "warnings": [],
        }

    def _deterministic_findings(self, state: dict[str, Any], context: EvaluationContext) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        for key, entry in state["progress"].items():
            if entry["status"] == "blocked" and entry["blocking"]:
                findings.append({"code": "blocking_progress", "severity": "blocking", "location": key, "message": entry["summary"]})
        round_state = current_round(state)
        relevant_evidence_ids = set(round_state["evidence_ids"])
        if round_state.get("decision"):
            relevant_evidence_ids.update(round_state["decision"]["evidence_refs"])
        current_artifact_ids = {
            ref
            for evidence in state["evidence"]
            if evidence["id"] in relevant_evidence_ids
            for ref in evidence["artifact_refs"]
        }
        for artifact in state["artifacts"]:
            if artifact["id"] not in current_artifact_ids or artifact["stability"] != "live":
                continue
            try:
                actual = context.inspect(artifact["path"])
            except RdlError as exc:
                findings.append({"code": exc.code, "severity": "blocking", "location": artifact["path"], "message": exc.message})
                continue
            if actual["size_bytes"] != artifact["size_bytes"] or actual["sha256"] != artifact["sha256"]:
                findings.append({"code": "artifact_drift", "severity": "blocking", "location": artifact["path"], "message": "live artifact changed since registration"})
        return sorted(
            findings,
            key=lambda item: (item.get("severity", ""), item.get("code", ""), item.get("location", ""), item.get("message", "")),
        )

    def _apply_artifacts(
        self,
        state: dict[str, Any],
        entries: dict[str, Any],
        context: EvaluationContext,
        assigned: dict[str, dict[str, str]],
    ) -> dict[str, str]:
        local: dict[str, str] = {}
        for key, value in entries.items():
            artifact_id = self._next_id(state, "artifact", "A")
            integrity = context.inspect(value["path"])
            record = deepcopy(value)
            record.update({"id": artifact_id, "round": state["round"], **integrity})
            state["artifacts"].append(record)
            local[key] = artifact_id
            assigned.setdefault("artifacts", {})[key] = artifact_id
        return local

    def _apply_evidence(
        self,
        state: dict[str, Any],
        entries: dict[str, Any],
        local_artifacts: dict[str, str],
        assigned: dict[str, dict[str, str]],
    ) -> dict[str, str]:
        local: dict[str, str] = {}
        existing_artifacts = {item["id"] for item in state["artifacts"]}
        for key, value in entries.items():
            evidence_id = self._next_id(state, "evidence", "E")
            record = deepcopy(value)
            record["artifact_refs"] = self._resolve_refs(
                record["artifact_refs"], local_artifacts, existing_artifacts, "artifact"
            )
            record.update({"id": evidence_id, "round": state["round"]})
            state["evidence"].append(record)
            current_round(state)["evidence_ids"].append(evidence_id)
            local[key] = evidence_id
            assigned.setdefault("evidence", {})[key] = evidence_id
        return local

    def _apply_events(self, state: dict[str, Any], entries: dict[str, Any], assigned: dict[str, dict[str, str]]) -> None:
        for key, value in entries.items():
            event_id = self._next_id(state, "event", "EV")
            record = deepcopy(value)
            record.update({"id": event_id, "round": state["round"]})
            state["events"].append(record)
            current_round(state)["event_ids"].append(event_id)
            assigned.setdefault("events", {})[key] = event_id

    def _apply_progress(self, state: dict[str, Any], entries: dict[str, Any], local_evidence: dict[str, str]) -> None:
        existing = {item["id"] for item in state["evidence"]}
        for key, value in entries.items():
            if value is None:
                state["progress"].pop(key, None)
                continue
            record = deepcopy(value)
            if "evidence_refs" in record:
                record["evidence_refs"] = self._resolve_refs(
                    record["evidence_refs"], local_evidence, existing, "evidence"
                )
            state["progress"][key] = record

    @staticmethod
    def _apply_factors(state: dict[str, Any], entries: dict[str, Any]) -> None:
        for key, value in entries.items():
            if value is None:
                state["factors"].pop(key, None)
            else:
                state["factors"][key] = deepcopy(value)

    @staticmethod
    def _resolve_refs(refs: list[str], local: dict[str, str], existing: set[str], kind: str) -> list[str]:
        resolved = []
        for ref in refs:
            durable = local.get(ref, ref)
            if durable not in existing:
                raise RdlError("unknown_reference", f"unknown {kind} reference: {ref}")
            resolved.append(durable)
        return list(dict.fromkeys(resolved))

    @staticmethod
    def _next_id(state: dict[str, Any], counter: str, prefix: str) -> str:
        state["counters"][counter] += 1
        return f"{prefix}{state['counters'][counter]:06d}"

    @staticmethod
    def _transition_action(state: dict[str, Any]) -> str | None:
        decision = current_round(state).get("decision")
        return decision.get("recommended_transition") if decision else None

    @staticmethod
    def _require_active(state: dict[str, Any]) -> None:
        if state["status"] != "active":
            raise RdlError("terminal_session", "terminal RDL sessions are read-only", status="blocked")

    @staticmethod
    def _expected(value: int | None) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise RdlError("invalid_version", "expected state version must be a positive integer")
        return value

    @staticmethod
    def _replay_or_check_version(
        state: dict[str, Any], expected: int, command_digest: str
    ) -> dict[str, Any] | None:
        if expected == state["state_version"]:
            return None
        last = state.get("last_mutation") or {}
        if (
            expected + 1 == state["state_version"]
            and last.get("base_version") == expected
            and last.get("request_digest") == command_digest
            and isinstance(last.get("receipt"), dict)
        ):
            return deepcopy(last["receipt"])
        raise RdlError(
            "state_version_conflict",
            "expected state version is stale",
            status="blocked",
            details={"expected": expected, "current": state["state_version"]},
        )

    @staticmethod
    def _generated_session_id() -> str:
        return f"session-{now_utc().replace(':', '').replace('T', '-').removesuffix('Z')}-{uuid.uuid4().hex[:8]}"

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
    canonical_json,
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


# A mission is resent to every fresh-context reviewer, so its size is paid per
# review. Warn past this point; never gate on it.
MISSION_SOFT_BYTES = 2 * 1024


class EvaluationContext:
    def __init__(self, root: Path):
        self.root = root
        self.cache: dict[str, dict[str, Any] | RdlError] = {}
        self.read_counts: dict[str, int] = {}

    def inspect(self, relative: str) -> dict[str, Any]:
        unresolved_key = f"unresolved:{relative}"
        if unresolved_key in self.cache:
            cached = self.cache[unresolved_key]
            if isinstance(cached, RdlError):
                raise cached
            return cached
        try:
            path = (self.root / relative).resolve()
        except (OSError, RuntimeError) as exc:
            error = RdlError(
                "artifact_unreadable",
                f"artifact path cannot be resolved: {relative}",
                status="blocked",
                details={"path": relative},
            )
            self.read_counts[relative] = self.read_counts.get(relative, 0) + 1
            self.cache[unresolved_key] = error
            raise error from exc
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
        if command == "handoff" and session_id is None:
            # No session is a fact, not a blocker: handoff is how a new turn asks.
            try:
                selected = self.repository.select_session_id(None)
            except RdlError as exc:
                if exc.code != "no_active_session":
                    raise
                return {"status": "ok", "session_status": "none", "warnings": []}
        else:
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
            warnings: list[str] = []
            if len(canonical_json(state["mission"]).encode("utf-8")) > MISSION_SOFT_BYTES:
                warnings.append("mission_over_soft_budget")
            receipt = {
                "status": "ok",
                "session_id": session_id,
                "round": 1,
                "state_version": 1,
                "assigned_ids": {},
                "effective_risk": "routine",
                "review_required": False,
                "transition_readiness": "needs_evidence",
                "warnings": warnings,
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
        before = deepcopy(state)
        before_round = current_round(before)
        review_result = delta.get("review_result")
        previous_subject = None
        context = EvaluationContext(self.root)
        if review_result:
            deterministic = self._deterministic_findings(before)
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
        self._apply_progress(updated, delta["progress_updates"], evidence_ids)
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
        effective_risk = "material" if reasons else "routine"
        if effective_risk == "material":
            round_state["material_required"] = True

        deterministic = self._deterministic_findings(updated)
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
            deterministic_findings=deterministic,
        )
        review_budget = self._review_budget(updated, transition_action, deterministic)
        receipt: dict[str, Any] = {
            "status": "ok",
            "session_id": updated["session_id"],
            "round": updated["round"],
            "state_version": target_version,
            "assigned_ids": assigned,
            "effective_risk": effective_risk,
            "review_required": readiness["status"] == "needs_review",
            "transition_readiness": readiness["status"],
            "warnings": self._receipt_warnings(readiness["warnings"], review_budget),
        }
        if review_budget is not None:
            receipt["review_budget"] = review_budget
        if reasons:
            receipt["risk_upgrade_reasons"] = reasons
        if current_subject is not None and readiness["status"] == "needs_review":
            receipt["review_subject_digest"] = current_subject
        updated["last_mutation"] = {
            "base_version": state["state_version"],
            "request_digest": command_digest,
            "receipt": deepcopy(receipt),
        }
        updated["state_digest"] = state_digest(updated)
        self.repository.cleanup(state["session_id"], state["state_version"])
        self.repository.commit(updated["session_id"], updated, rendering.render_views(updated))
        return receipt

    def _next(self, state: dict[str, Any], expected: int | None) -> dict[str, Any]:
        request = {"expected_state_version": self._expected(expected)}
        command_digest = request_digest("next", state["session_id"], request)
        replay = self._replay_or_check_version(state, request["expected_state_version"], command_digest)
        if replay is not None:
            return replay
        self._require_active(state)
        readiness = self._readiness(state, "next")
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
        # --reason only carries meaning for an abandon; ignore it elsewhere so a
        # harmless extra flag never blocks a close, and replay digests stay stable.
        if outcome == "abandoned":
            if reason is not None:
                request["reason"] = reason.strip()
            if not request.get("reason"):
                raise RdlError("missing_abandon_reason", "abandoned close requires --reason")
        command_digest = request_digest("close", state["session_id"], request)
        replay = self._replay_or_check_version(state, version, command_digest)
        if replay is not None:
            return replay
        self._require_active(state)
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
            readiness = self._readiness(state, "close")
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
        rendering.handoff(
            updated,
            {"status": readiness, "blockers": [], "warnings": []},
        )
        self.repository.cleanup(previous["session_id"], previous["state_version"])
        self.repository.commit(updated["session_id"], updated, rendering.render_views(updated))
        return receipt

    def _handoff(self, state: dict[str, Any]) -> dict[str, Any]:
        action = self._transition_action(state)
        findings = self._deterministic_findings(state)
        readiness = self._readiness(state, action, deterministic_findings=findings)
        return rendering.handoff(state, readiness, self._review_budget(state, action, findings))

    def _review(self, state: dict[str, Any], action: str | None) -> dict[str, Any]:
        if action not in {"next", "close"}:
            raise RdlError("invalid_review_action", "review action must be next or close")
        if self._transition_action(state) != action:
            raise RdlError("review_action_mismatch", "review action does not match the current decision", status="blocked")
        findings = self._deterministic_findings(state)
        readiness = self._readiness(state, action, deterministic_findings=findings)
        if readiness["status"] != "needs_review":
            raise RdlError(
                "review_not_required",
                "the current subject does not require review",
                status="blocked",
                details=readiness,
            )
        return rendering.review_pack(state, action, findings)

    def _doctor(self, state: dict[str, Any], diagnostics: bool) -> dict[str, Any]:
        action = self._transition_action(state)
        findings = self._deterministic_findings(state)
        readiness = self._readiness(
            state,
            action,
            deterministic_findings=findings,
        )
        review_budget = self._review_budget(state, action, findings)
        handoff_projection = rendering.handoff_diagnostics(state, readiness, review_budget)
        review_projection = None
        if state["status"] == "active" and readiness["status"] == "needs_review":
            review_projection = rendering.review_pack_diagnostics(
                state,
                action,
                findings,
            )
            if review_projection["hard_limit_exceeded"]:
                findings.append(
                    {
                        "code": "review_pack_over_budget",
                        "severity": "blocking",
                        "message": "the required semantic review pack exceeds its hard budget",
                    }
                )
            elif review_projection["soft_limit_exceeded"]:
                findings.append(
                    {
                        "code": "review_pack_soft_budget_exceeded",
                        "severity": "warning",
                        "message": "the required semantic review pack exceeds its soft budget",
                    }
                )
        expected_views = {key: value.encode("utf-8") for key, value in rendering.render_views(state).items()}
        actual_views = self.repository.read_views(state["session_id"])
        if actual_views != expected_views:
            findings.append({"code": "derived_view_drift", "severity": "warning", "message": "derived views differ from state.json"})
        generation = self.repository.generation_diagnostics(state["session_id"], state["state_version"])
        if generation["temporary"] or generation["unreferenced"]:
            findings.append({"code": "orphan_generations", "severity": "warning", "message": "temporary or unreferenced generations exist"})
        if state["status"] != "active":
            findings.extend(self._terminal_findings(state))
        result: dict[str, Any] = {
            "status": "blocked" if any(item["severity"] == "blocking" for item in findings) else "ok",
            "session_id": state["session_id"],
            "state_version": state["state_version"],
            "session_status": state["status"],
            "findings": findings,
        }
        if diagnostics:
            projections = {"handoff": handoff_projection}
            if review_projection is not None:
                projections["review"] = review_projection
            result["diagnostics"] = {
                "generations": generation,
                "projections": projections,
            }
        return result

    def _terminal_findings(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Probe a closed session for the three properties its close receipt claims.

        Every probe calls an internal method rather than execute(): execute()
        takes the session lock that doctor already holds, and each probe returns
        or raises during version/status checks, long before any commit.
        """
        findings: list[dict[str, Any]] = []
        last = state.get("last_mutation") or {}
        base_version = last.get("base_version")
        stored = last.get("receipt")
        if not isinstance(base_version, int) or not isinstance(stored, dict):
            return [
                {
                    "code": "terminal_replay_unavailable",
                    "severity": "blocking",
                    "message": "the terminal session has no replayable close receipt",
                }
            ]

        # Replay reconstructs the close request from what the state now says
        # happened. A reconstruction that no longer digests to the persisted
        # request means the state and its receipt disagree about the close.
        if state["status"] == "abandoned":
            outcome, reason = "abandoned", self._abandon_reason(state)
        else:
            outcome, reason = state["status"].removeprefix("closed-"), None
        try:
            self._close(deepcopy(state), base_version, outcome, reason)
        except RdlError:
            findings.append(
                {
                    "code": "terminal_replay_mismatch",
                    "severity": "blocking",
                    "message": "the close request rebuilt from state does not replay to the persisted receipt",
                }
            )
        expected_receipt = {
            "session_id": state["session_id"],
            "round": state["round"],
            "state_version": state["state_version"],
            "transition_readiness": "terminal",
        }
        if {key: stored.get(key) for key in expected_receipt} != expected_receipt:
            findings.append(
                {
                    "code": "terminal_receipt_incoherent",
                    "severity": "blocking",
                    "message": "the persisted close receipt disagrees with the state it closed",
                }
            )

        current = state["state_version"]
        mutations = (
            ("apply", lambda: self._apply(deepcopy(state), {"expected_state_version": current})),
            ("next", lambda: self._next(deepcopy(state), current)),
            ("close", lambda: self._close(deepcopy(state), current, "inconclusive", None)),
        )
        for command, probe in mutations:
            if self._rejection_code(probe) != "terminal_session":
                findings.append(
                    {
                        "code": "terminal_mutation_not_rejected",
                        "severity": "blocking",
                        "message": f"{command} was not rejected as terminal",
                    }
                )

        stale = lambda: self._apply(deepcopy(state), {"expected_state_version": base_version})
        if self._rejection_code(stale) != "state_version_conflict":
            findings.append(
                {
                    "code": "stale_apply_not_rejected",
                    "severity": "blocking",
                    "message": "an apply at the pre-close version was not rejected as stale",
                }
            )
        return findings

    @staticmethod
    def _abandon_reason(state: dict[str, Any]) -> str | None:
        for event in reversed(state["events"]):
            if event["kind"] == "abandoned":
                return event["summary"]
        return None

    @staticmethod
    def _rejection_code(probe) -> str | None:
        try:
            probe()
        except RdlError as exc:
            return exc.code
        return None

    def _readiness(
        self,
        state: dict[str, Any],
        action: str | None,
        *,
        deterministic_findings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if state["status"] != "active":
            return {"status": "terminal", "blockers": [], "warnings": []}
        if action not in {"next", "close"}:
            return {"status": "needs_evidence", "blockers": ["missing_transition_decision"], "warnings": []}
        round_state = current_round(state)
        findings = deterministic_findings
        if findings is None:
            findings = self._deterministic_findings(state)
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

    @staticmethod
    def _receipt_warnings(warnings: list[str], review_budget: dict[str, Any] | None) -> list[str]:
        result = list(warnings)
        if review_budget is None:
            return result
        if review_budget["hard_limit_exceeded"]:
            result.append("review_pack_over_budget")
        elif review_budget["soft_limit_exceeded"]:
            result.append("review_pack_soft_budget_exceeded")
        return result

    @staticmethod
    def _review_budget(
        state: dict[str, Any], action: str | None, deterministic_findings: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if state["status"] != "active" or action not in {"next", "close"}:
            return None
        diagnostics = rendering.review_pack_diagnostics(state, action, deterministic_findings)
        return {
            "action": action,
            "size_bytes": diagnostics["size_bytes"],
            "soft_limit_bytes": diagnostics["soft_limit_bytes"],
            "hard_limit_bytes": diagnostics["hard_limit_bytes"],
            "soft_limit_exceeded": diagnostics["soft_limit_exceeded"],
            "hard_limit_exceeded": diagnostics["hard_limit_exceeded"],
        }

    def _deterministic_findings(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []
        transition_action = self._transition_action(state)
        for key, entry in state["progress"].items():
            if entry["status"] == "blocked" and entry["blocking"]:
                findings.append({"code": "blocking_progress", "severity": "blocking", "location": key, "message": entry["summary"]})
            if transition_action == "close" and entry["status"] == "active":
                findings.append(
                    {
                        "code": "unreconciled_active_progress",
                        "severity": "blocking",
                        "location": key,
                        "message": entry["summary"],
                    }
                )
        round_state = current_round(state)
        findings.extend(rendering.missing_review_reference_findings(state, round_state))
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

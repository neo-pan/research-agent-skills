"""Session safety assessment for RDL."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import integrity, store
from .documents import validate as validate_document
from .model import AuditResult, Blocker, SessionMode, SessionPhase, SessionState, SessionStatus
from .protocol import descriptor


@dataclass(frozen=True)
class RepairScopeAssessment:
    errors: tuple[Blocker, ...]
    blockers: tuple[Blocker, ...]

    @property
    def ok(self) -> bool:
        return not self.errors and not self.blockers


def audit(session: Any) -> AuditResult:
    errors: list[Blocker] = []
    blockers: list[Blocker] = []

    if session.state_error is not None:
        errors.append(session.state_error)
        return AuditResult(tuple(errors), tuple(blockers))

    _validate_state_values(session.root / "state.json", session.state, errors, session.raw_state)
    if errors:
        return AuditResult(tuple(errors), tuple(blockers))

    _validate_session_lock(session.root / ".lock", blockers)

    mission_file = session.state.mission_file
    if not (session.root / mission_file).is_file():
        blockers.append(
            Blocker(
                "missing_mission_file",
                mission_file,
                "mission file does not exist.",
                "Restore the mission file or repair the session.",
            )
        )

    required_files = (
        "integrity.json",
        *(
            file_name
            for file_name in descriptor.required_session_files()
            if file_name not in {"state.json", "mission.md"}
        ),
    )
    for file_name in required_files:
        if not (session.root / file_name).is_file():
            blockers.append(
                Blocker(
                    "missing_required_file",
                    file_name,
                    f"{file_name} is missing.",
                    f"Restore {file_name}.",
                )
            )

    progress_path = session.root / "progress.md"
    if progress_path.is_file():
        blockers.extend(validate_document("progress", progress_path))

    manifest_path = session.root / "artifact-manifest.json"
    if manifest_path.is_file():
        _validate_artifact_manifest(manifest_path, errors, blockers)

    integrity_path = session.root / "integrity.json"
    if integrity_path.is_file():
        integrity.validate(session, errors, blockers)

    current_round = session.round_dir()
    round_rel = f"rounds/{session.state.round:03d}"
    if not current_round.is_dir():
        blockers.append(
            Blocker(
                "missing_round_dir",
                round_rel,
                "active round directory is missing.",
                "Restore or repair the active round directory.",
            )
        )
    elif not (current_round / "prompt.md").is_file():
        blockers.append(
            Blocker(
                "missing_prompt",
                f"{round_rel}/prompt.md",
                "current round prompt.md is missing.",
                "Regenerate or restore prompt.md.",
            )
        )

    return AuditResult(tuple(errors), tuple(blockers))


def state_errors(session: Any) -> tuple[Blocker, ...]:
    if session.state_error is not None:
        return (session.state_error,)
    errors: list[Blocker] = []
    _validate_state_values(session.root / "state.json", session.state, errors, session.raw_state)
    return tuple(errors)


def lock_owner_pid(path: Path) -> int | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line.startswith("pid="):
            continue
        value = line.removeprefix("pid=").strip()
        if value.isdigit():
            return int(value)
        return None
    return None


def lock_conflict(path: Path) -> Blocker:
    blocker = lock_blocker(path)
    return blocker if blocker is not None else _session_locked_blocker()


def lock_blocker(path: Path) -> Blocker | None:
    if not path.is_file():
        return None
    blockers: list[Blocker] = []
    _validate_session_lock(path, blockers)
    return blockers[0] if blockers else None


def assess_repair_scope(session: Any) -> RepairScopeAssessment:
    errors: list[Blocker] = []
    blockers: list[Blocker] = []
    _validate_repair_structure(session, errors, blockers)
    if errors or blockers:
        return RepairScopeAssessment(tuple(errors), tuple(blockers))

    manifest_path = session.root / "integrity.json"
    manifest = _usable_manifest(manifest_path)
    if manifest is None:
        errors.append(
            Blocker(
                "unsafe_integrity_manifest",
                "integrity.json",
                "repair requires a usable integrity manifest before refreshing trusted records.",
                "Restore integrity.json from a trusted source or start a new session.",
            )
        )
        return RepairScopeAssessment(tuple(errors), tuple(blockers))

    _validate_manifest_completeness(session, manifest, errors)
    _validate_existing_entries(session, manifest, errors)
    return RepairScopeAssessment(tuple(errors), tuple(blockers))


def _validate_state_values(path: Path, state: SessionState, errors: list[Blocker], raw_state: Any | None = None) -> None:
    def add(code: str, message: str, next_action: str = "Repair state.json explicitly.") -> None:
        errors.append(Blocker(code, str(path), message, next_action))

    raw = raw_state if isinstance(raw_state, dict) else {}
    raw_mode = raw.get("mode") if raw_state is not None else state.mode.value
    raw_phase = raw.get("phase") if raw_state is not None else state.phase.value
    raw_status = raw.get("status") if raw_state is not None else state.status.value
    raw_round = raw.get("round", state.round)

    raw_schema = raw.get("schema_version", state.schema_version)
    if not _strict_int(raw_schema) or raw_schema != 1:
        add("unsupported_schema", "schema_version must be 1.", "Use a supported RDL session or migrate explicitly.")
    raw_session_id = raw.get("session_id", state.session_id)
    if not _non_empty_str(raw_session_id):
        add("missing_session_id", "session_id is missing.")
    if raw_mode not in {mode.value for mode in SessionMode}:
        add("invalid_mode", "mode must be research or build.")
    if raw_phase not in {phase.value for phase in SessionPhase}:
        add("invalid_phase", "phase is unsupported.")
    if not _strict_int(raw_round) or raw_round < 1:
        add("invalid_round", "round must be a positive number.")
    if raw_status not in {status.value for status in SessionStatus}:
        add("invalid_status", "status is unsupported.")
    raw_mission_file = raw.get("mission_file", state.mission_file)
    if not _non_empty_str(raw_mission_file):
        add("missing_mission_file_field", "mission_file is missing.")


def _validate_artifact_manifest(path: Path, errors: list[Blocker], blockers: list[Blocker]) -> None:
    try:
        data = store.read_json(path)
    except json.JSONDecodeError:
        errors.append(
            Blocker(
                "invalid_artifact_manifest_json",
                "artifact-manifest.json",
                "artifact-manifest.json is not valid JSON.",
                "Fix artifact-manifest.json.",
            )
        )
        return
    if not isinstance(data, dict) or not isinstance(data.get("artifacts"), list):
        blockers.append(
            Blocker(
                "invalid_artifact_manifest",
                "artifact-manifest.json",
                "artifact-manifest.json must be an object with an artifacts array.",
                "Fix artifact-manifest.json.",
            )
        )
        return
    artifacts = data["artifacts"]
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            blockers.append(_invalid_artifact_entry())
            continue
        has_path_or_url = _optional_non_empty_str(artifact.get("path")) or _optional_non_empty_str(artifact.get("url"))
        if not all(_non_empty_str(artifact.get(field)) for field in ("id", "kind", "description")):
            blockers.append(_invalid_artifact_entry())
        elif not _strict_int(artifact.get("round")) or artifact["round"] < 1 or not has_path_or_url:
            blockers.append(_invalid_artifact_entry())


def _invalid_artifact_entry() -> Blocker:
    return Blocker(
        "invalid_artifact_entry",
        "artifact-manifest.json",
        "artifact entries need id, kind, round, description, and path or url.",
        "Fix artifact entries or remove invalid artifacts.",
    )


def _validate_session_lock(path: Path, blockers: list[Blocker]) -> None:
    if not path.is_file():
        return
    pid = lock_owner_pid(path)
    if pid == os.getpid():
        return
    if pid is not None and _process_alive(pid):
        blockers.append(_session_locked_blocker())
    else:
        blockers.append(
            Blocker(
                "stale_lock",
                ".lock",
                "RDL session lock exists but the owning process is gone.",
                "Inspect the interrupted command, then run rdl repair or remove .lock manually.",
            )
        )


def _session_locked_blocker() -> Blocker:
    return Blocker(
        "session_locked",
        ".lock",
        "RDL session is locked by another process.",
        "Wait for the command to finish, then retry.",
    )


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _validate_repair_structure(session: Any, errors: list[Blocker], blockers: list[Blocker]) -> None:
    if session.state_error is not None:
        errors.append(session.state_error)
        return
    audit_result = audit(session)
    for error in audit_result.errors:
        if _repair_scope_owns(error.code):
            continue
        errors.append(error)

    required = (
        session.state.mission_file,
        "factors.md",
        "artifact-manifest.json",
        "decision-ledger.md",
        "progress.md",
    )
    for relative in required:
        if relative and not (session.root / relative).is_file():
            blockers.append(
                Blocker(
                    "unsafe_missing_protocol_file",
                    relative,
                    f"{relative} is missing and cannot be safely repaired.",
                    f"Restore {relative} from a known-good source.",
                )
            )

    round_relative = f"rounds/{session.state.round:03d}"
    if not (session.root / round_relative).is_dir():
        blockers.append(
            Blocker(
                "unsafe_missing_round_dir",
                round_relative,
                "active round directory is missing and cannot be safely repaired.",
                "Restore the active round directory.",
            )
        )

    for blocker in audit_result.blockers:
        if _repair_scope_owns(blocker.code):
            continue
        if blocker.code in {"missing_required_file", "missing_mission_file", "missing_round_dir", "missing_prompt"}:
            continue
        blockers.append(blocker)


def _repair_scope_owns(code: str) -> bool:
    return code.startswith("integrity_") or code in {
        "invalid_integrity_json",
        "invalid_integrity_manifest",
        "empty_integrity_manifest",
        "missing_integrity_entry",
        "duplicate_integrity_entry",
        "unexpected_integrity_entry",
        "integrity_policy_mismatch",
        "missing_integrity_file",
        "missing_managed_block",
    }


def _usable_manifest(path: Path) -> dict[str, Any] | None:
    try:
        data = store.read_json(path)
    except Exception:
        return None
    if not integrity.manifest_shape_valid(data):
        return None
    if not data["entries"]:
        return None
    return data


def _validate_manifest_completeness(session: Any, manifest: dict[str, Any], errors: list[Blocker]) -> None:
    expected_policy = integrity.expected_policies(session)
    seen: dict[str, int] = {}
    for entry in manifest["entries"]:
        relative = entry["path"]
        seen[relative] = seen.get(relative, 0) + 1
        if not integrity.session_path_known(session, relative):
            errors.append(
                Blocker(
                    "unsafe_integrity_entry",
                    relative,
                    "integrity.json contains a path outside the RDL protocol set.",
                    "Remove the unexpected entry manually before repair.",
                )
            )
            continue
        expected = expected_policy.get(relative)
        if expected is not None and entry["policy"] != expected and expected in {"cli_owned", "append_only", "managed_prefix"}:
            errors.append(
                Blocker(
                    "integrity_policy_mismatch",
                    relative,
                    "integrity entry policy does not match the expected RDL protocol policy.",
                    "Restore the expected integrity policy or run rdl repair when available.",
                )
            )

    for relative, policy in expected_policy.items():
        count = seen.get(relative, 0)
        if count > 1:
            errors.append(
                Blocker(
                    "duplicate_integrity_entry",
                    relative,
                    "integrity.json contains duplicate entries for the same protocol file.",
                    "Remove duplicate integrity entries or run rdl repair when available.",
                )
            )
        elif count == 0 and policy in {"cli_owned", "append_only", "managed_prefix"}:
            errors.append(
                Blocker(
                    "missing_integrity_entry",
                    relative,
                    "integrity.json is missing an expected protected protocol-file entry.",
                    "Restore the missing integrity entry or run rdl repair when available.",
                )
            )
        elif count == 0 and policy == "human_owned" and (session.root / relative).is_file():
            errors.append(
                Blocker(
                    "missing_integrity_entry",
                    relative,
                    "integrity.json is missing an expected human-owned protocol-file entry needed for repair validation.",
                    "Restore the missing integrity entry or review the file manually before repair.",
                )
            )

    _validate_state_derived_history(session, seen, errors)


def _validate_state_derived_history(session: Any, seen: dict[str, int], errors: list[Blocker]) -> None:
    for round_number in range(1, session.state.round):
        round_prefix = f"rounds/{round_number:03d}"
        for file_name in descriptor.completed_round_files(session.state.mode):
            relative = f"{round_prefix}/{file_name}"
            if (session.root / relative).is_file():
                continue
            if seen.get(relative, 0) == 0:
                errors.append(
                    Blocker(
                        "unsafe_missing_protocol_file",
                        relative,
                        "Missing prior-round protocol file cannot be safely repaired.",
                        f"Restore {relative} from a known-good source.",
                    )
                )


def _validate_existing_entries(session: Any, manifest: dict[str, Any], errors: list[Blocker]) -> None:
    active_prompt = f"rounds/{session.state.round:03d}/prompt.md"
    for entry in manifest["entries"]:
        relative = entry["path"]
        if not integrity.session_path_known(session, relative):
            continue
        path = session.root / relative
        if not path.is_file():
            if relative == active_prompt and session.state.round == 1:
                continue
            errors.append(
                Blocker(
                    "unsafe_missing_protocol_file",
                    relative,
                    "Missing protocol file cannot be safely repaired.",
                    f"Restore {relative} from a known-good source.",
                )
            )
            continue
        policy = entry["policy"]
        if policy == "cli_owned":
            if integrity.file_sha256(path) != entry["sha256"]:
                errors.append(_unsafe("unsafe_cli_owned_change", relative, "CLI-owned protocol file hash changed."))
        elif policy == "append_only":
            data = path.read_bytes()
            recorded_size = entry["size"]
            if len(data) < recorded_size or integrity.bytes_sha256(data[:recorded_size]) != entry["prefix_sha256"]:
                errors.append(_unsafe("unsafe_append_only_change", relative, "Append-only protocol file prefix changed."))
        elif policy == "managed_prefix":
            block = integrity.managed_block(path.read_text(encoding="utf-8"))
            if block is None or integrity.bytes_sha256(block.encode("utf-8")) != entry["managed_sha256"]:
                errors.append(_unsafe("unsafe_managed_prefix_change", relative, "Managed-prefix protocol file block changed."))
        elif policy == "human_owned":
            if integrity.file_sha256(path) != entry["sha256"]:
                errors.append(_unsafe("unsafe_human_owned_change", relative, "Human-owned protocol file hash changed."))
        else:
            errors.append(
                Blocker(
                    "unsafe_integrity_entry",
                    relative,
                    "integrity entry policy is unsupported.",
                    "Fix integrity.json before repair.",
                )
            )


def _unsafe(code: str, relative: str, message: str) -> Blocker:
    return Blocker(code, relative, message, f"Restore {relative} from a known-good source before repair.")


def _strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _optional_non_empty_str(value: Any) -> bool:
    if value is None:
        return False
    return _non_empty_str(value)

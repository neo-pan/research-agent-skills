"""Session safety assessment for RDL."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import integrity, store
from .documents import validate as validate_document
from .model import AuditResult, Blocker, SessionMode, SessionPhase, SessionState, SessionStatus
from .protocol import descriptor


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
    errors: list[Blocker] = []
    _validate_state_values(session.root / "state.json", session.state, errors, session.raw_state)
    return tuple(errors)


def lock_owner_pid(path: Path) -> int | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("pid="):
            continue
        value = line.removeprefix("pid=").strip()
        if value.isdigit():
            return int(value)
        return None
    return None


def lock_conflict(path: Path) -> Blocker:
    blockers: list[Blocker] = []
    _validate_session_lock(path, blockers)
    return blockers[0] if blockers else _session_locked_blocker()


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
    except OSError:
        return False
    return True


def _strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _optional_non_empty_str(value: Any) -> bool:
    if value is None:
        return False
    return _non_empty_str(value)

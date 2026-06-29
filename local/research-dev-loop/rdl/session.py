"""Session lifecycle and layout inspection for RDL."""

from __future__ import annotations

import json
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import store
from .documents import validate as validate_document
from .model import AuditResult, Blocker, SessionMode, SessionPhase, SessionState, SessionStatus
from .protocol import descriptor


@dataclass(frozen=True)
class Session:
    root: Path
    state: SessionState
    state_error: Blocker | None = None
    raw_state: Any | None = None

    def path(self, relative: str) -> Path:
        return self.root / relative

    def round_dir(self, round: int | None = None) -> Path:
        round_number = round if round is not None else max(self.state.round, 1)
        return self.root / "rounds" / f"{round_number:03d}"

    def audit(self) -> AuditResult:
        errors: list[Blocker] = []
        blockers: list[Blocker] = []

        if self.state_error is not None:
            errors.append(self.state_error)
            return AuditResult(tuple(errors), tuple(blockers))

        _validate_state_values(self.root / "state.json", self.state, errors, self.raw_state)
        if errors:
            return AuditResult(tuple(errors), tuple(blockers))

        _validate_session_lock(self.root / ".lock", blockers)

        mission_file = self.state.mission_file
        if not (self.root / mission_file).is_file():
            blockers.append(
                Blocker(
                    "missing_mission_file",
                    mission_file,
                    "mission file does not exist.",
                    "Restore the mission file or repair the session.",
                )
            )

        for file_name in ("integrity.json", "factors.md", "artifact-manifest.json", "decision-ledger.md", "progress.md"):
            if not (self.root / file_name).is_file():
                blockers.append(
                    Blocker(
                        "missing_required_file",
                        file_name,
                        f"{file_name} is missing.",
                        f"Restore {file_name}.",
                    )
                )

        progress_path = self.root / "progress.md"
        if progress_path.is_file():
            blockers.extend(validate_document("progress", progress_path))

        manifest_path = self.root / "artifact-manifest.json"
        if manifest_path.is_file():
            _validate_artifact_manifest(manifest_path, errors, blockers)

        integrity_path = self.root / "integrity.json"
        if integrity_path.is_file():
            _validate_integrity_manifest(self, integrity_path, errors, blockers)

        current_round = self.round_dir()
        round_rel = f"rounds/{self.state.round:03d}"
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


class SessionStore:
    def __init__(self, repo_root: str | Path):
        self.repo_root = Path(repo_root)
        self.sessions_root = self.repo_root / ".rdl" / "sessions"

    @classmethod
    def cwd(cls) -> "SessionStore":
        return cls(Path.cwd())

    def active_session(self) -> Session | None:
        sessions = self._sessions()
        active: list[Session] = []
        fallback_error: Session | None = None

        for session_dir in sessions:
            session = self._load_session(session_dir)
            if session.state_error is not None:
                if fallback_error is None:
                    fallback_error = session
                return fallback_error
            if _state_value_errors(session):
                return session
            if session.state.status == SessionStatus.ACTIVE:
                active.append(session)

        if len(active) > 1:
            raise ValueError("multiple active RDL sessions exist")
        if active:
            return active[0]
        return fallback_error

    def _sessions(self) -> list[Path]:
        if not self.sessions_root.is_dir():
            return []
        return sorted(path for path in self.sessions_root.iterdir() if path.is_dir())

    def _load_session(self, session_dir: Path) -> Session:
        state_path = session_dir / "state.json"
        if not state_path.is_file():
            return Session(session_dir, _placeholder_state(session_dir.name), _state_error("missing_state", state_path))
        try:
            state = SessionState.from_json(store.read_json(state_path))
        except json.JSONDecodeError:
            return Session(session_dir, _placeholder_state(session_dir.name), _state_error("invalid_state_json", state_path))
        except ValueError:
            try:
                raw = store.read_json(state_path)
            except Exception:
                raw = {}
            state = _partial_state(raw, session_dir.name)
            return Session(session_dir, state, raw_state=raw)
        return Session(session_dir, state, raw_state=store.read_json(state_path))


def _placeholder_state(session_id: str) -> SessionState:
    return SessionState(
        schema_version=1,
        session_id=session_id,
        mode=SessionMode.RESEARCH,
        phase=SessionPhase.PLAN,
        round=1,
        status=SessionStatus.ACTIVE,
        mission_file="mission.md",
    )


def _partial_state(raw: Any, fallback_session_id: str) -> SessionState:
    if not isinstance(raw, dict):
        return _placeholder_state(fallback_session_id)
    try:
        mode = SessionMode(raw.get("mode", "research"))
    except ValueError:
        mode = SessionMode.RESEARCH
    try:
        phase = SessionPhase(raw.get("phase", "plan"))
    except ValueError:
        phase = SessionPhase.PLAN
    try:
        status = SessionStatus(raw.get("status", "active"))
    except ValueError:
        status = SessionStatus.ACTIVE
    round_value = raw.get("round")
    if not _strict_int(round_value):
        round_value = 0
    return SessionState(
        schema_version=raw.get("schema_version") if _strict_int(raw.get("schema_version")) else 0,
        session_id=raw.get("session_id") if isinstance(raw.get("session_id"), str) else "",
        mode=mode,
        phase=phase,
        round=round_value,
        status=status,
        mission_file=raw.get("mission_file") if isinstance(raw.get("mission_file"), str) else "",
    )


def _state_error(code: str, path: Path) -> Blocker:
    if code == "missing_state":
        return Blocker(code, str(path), "state.json is missing.", "Restore state.json or abandon the session.")
    return Blocker(code, str(path), "state.json is not valid JSON.", "Repair state.json explicitly.")


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


def _state_value_errors(session: Session) -> tuple[Blocker, ...]:
    errors: list[Blocker] = []
    _validate_state_values(session.root / "state.json", session.state, errors, session.raw_state)
    return tuple(errors)


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
    pid = _lock_owner_pid(path)
    if pid == os.getpid():
        return
    if pid is not None and _process_alive(pid):
        blockers.append(
            Blocker(
                "session_locked",
                ".lock",
                "RDL session is locked by another process.",
                "Wait for the command to finish, then retry.",
            )
        )
    else:
        blockers.append(
            Blocker(
                "stale_lock",
                ".lock",
                "RDL session lock exists but the owning process is gone.",
                "Inspect the interrupted command, then run rdl repair or remove .lock manually.",
            )
        )


def _lock_owner_pid(path: Path) -> int | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("pid="):
            continue
        value = line.removeprefix("pid=").strip()
        if value.isdigit():
            return int(value)
        return None
    return None


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _validate_integrity_manifest(session: Session, path: Path, errors: list[Blocker], blockers: list[Blocker]) -> None:
    try:
        data = store.read_json(path)
    except json.JSONDecodeError:
        errors.append(
            Blocker(
                "invalid_integrity_json",
                "integrity.json",
                "integrity.json is not valid JSON.",
                "Repair integrity.json explicitly.",
            )
        )
        return

    if not _integrity_shape_valid(data):
        errors.append(
            Blocker(
                "invalid_integrity_manifest",
                "integrity.json",
                "integrity.json entries are malformed.",
                "Repair integrity.json explicitly.",
            )
        )
        return

    expected_policy = _expected_integrity_policies(session)
    seen: dict[str, int] = {relative: 0 for relative in expected_policy}
    entries = data["entries"]
    if not entries:
        errors.append(
            Blocker(
                "empty_integrity_manifest",
                "integrity.json",
                "integrity.json has no protocol-file entries.",
                "Restore integrity.json or run rdl repair when available.",
            )
        )

    for entry in entries:
        relative = entry["path"]
        policy = entry["policy"]
        if not descriptor.path_known(relative):
            if (session.root / relative).is_file():
                errors.append(
                    Blocker(
                        "unexpected_integrity_entry",
                        relative,
                        "integrity.json contains a path outside the expected RDL protocol set.",
                        "Remove the unexpected integrity entry or run rdl repair when available.",
                    )
                )
            continue
        if relative in seen:
            seen[relative] += 1
        expected = expected_policy.get(relative)
        if expected is not None and policy != expected:
            errors.append(
                Blocker(
                    "integrity_policy_mismatch",
                    relative,
                    "integrity entry policy does not match the expected RDL protocol policy.",
                    "Restore the expected integrity policy or run rdl repair when available.",
                )
            )

        file_path = session.root / relative
        if not file_path.is_file():
            blockers.append(
                Blocker(
                    "missing_integrity_file",
                    relative,
                    "integrity entry path is missing.",
                    f"Restore {relative} or run rdl repair when available.",
                )
            )
            continue
        _validate_integrity_entry_hash(file_path, entry, errors)

    for relative, count in seen.items():
        policy = expected_policy[relative]
        if count == 0 and policy in {"cli_owned", "append_only", "managed_prefix"}:
            errors.append(
                Blocker(
                    "missing_integrity_entry",
                    relative,
                    "integrity.json is missing an expected protected protocol-file entry.",
                    "Restore the missing integrity entry or run rdl repair when available.",
                )
            )
        elif count > 1:
            errors.append(
                Blocker(
                    "duplicate_integrity_entry",
                    relative,
                    "integrity.json contains duplicate entries for the same protocol file.",
                    "Remove duplicate integrity entries or run rdl repair when available.",
                )
            )


def _integrity_shape_valid(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("schema_version") != 1:
        return False
    if not isinstance(data.get("session_id"), str) or not data["session_id"]:
        return False
    entries = data.get("entries")
    if not isinstance(entries, list):
        return False
    digest_re = re.compile(r"^[0-9a-f]{64}$")
    for entry in entries:
        if not isinstance(entry, dict):
            return False
        if not isinstance(entry.get("path"), str) or not entry["path"]:
            return False
        if entry.get("policy") not in {"cli_owned", "append_only", "managed_prefix", "human_owned"}:
            return False
        if not isinstance(entry.get("sha256"), str) or not digest_re.fullmatch(entry["sha256"]):
            return False
        if entry["policy"] == "append_only":
            if not _strict_int(entry.get("size")) or entry["size"] < 0:
                return False
            if not isinstance(entry.get("prefix_sha256"), str) or not digest_re.fullmatch(entry["prefix_sha256"]):
                return False
        if entry["policy"] == "managed_prefix":
            if not isinstance(entry.get("managed_sha256"), str) or not digest_re.fullmatch(entry["managed_sha256"]):
                return False
    return True


def _expected_integrity_policies(session: Session) -> dict[str, str]:
    paths = [
        "state.json",
        session.state.mission_file,
        "factors.md",
        "artifact-manifest.json",
        "decision-ledger.md",
        "progress.md",
    ]
    if (session.root / "final-report.md").is_file():
        paths.append("final-report.md")
    rounds_dir = session.root / "rounds"
    if rounds_dir.is_dir():
        for round_dir in sorted(path for path in rounds_dir.iterdir() if path.is_dir()):
            for file_name in descriptor.round_file_names():
                path = round_dir / file_name
                if path.is_file():
                    paths.append(str(path.relative_to(session.root)))
    return {relative: descriptor.policy_for_path(relative) for relative in paths if relative}


def _validate_integrity_entry_hash(path: Path, entry: dict[str, Any], errors: list[Blocker]) -> None:
    policy = entry["policy"]
    relative = entry["path"]
    if policy == "cli_owned":
        if _sha256(path.read_bytes()) != entry["sha256"]:
            errors.append(
                Blocker(
                    "integrity_violation_cli_owned",
                    relative,
                    "CLI-owned protocol file hash changed.",
                    f"Restore {relative} or run rdl repair when available.",
                )
            )
    elif policy == "append_only":
        data = path.read_bytes()
        recorded_size = entry["size"]
        if len(data) < recorded_size:
            errors.append(
                Blocker(
                    "integrity_violation_append_only",
                    relative,
                    "Append-only protocol file is shorter than its recorded size.",
                    "Restore the append-only prefix or run rdl repair when available.",
                )
            )
        elif _sha256(data[:recorded_size]) != entry["prefix_sha256"]:
            errors.append(
                Blocker(
                    "integrity_violation_append_only",
                    relative,
                    "Append-only protocol file prefix changed.",
                    "Restore the append-only prefix or run rdl repair when available.",
                )
            )
    elif policy == "managed_prefix":
        block = _managed_block(path.read_text(encoding="utf-8"))
        if block is None:
            errors.append(
                Blocker(
                    "missing_managed_block",
                    relative,
                    "Managed-prefix protocol file is missing required managed markers.",
                    "Restore the generated managed block or run rdl repair when available.",
                )
            )
        elif _sha256(block.encode("utf-8")) != entry["managed_sha256"]:
            errors.append(
                Blocker(
                    "integrity_violation_managed_prefix",
                    relative,
                    "Managed-prefix protocol file block changed.",
                    "Restore the generated managed block or run rdl repair when available.",
                )
            )


def _managed_block(text: str) -> str | None:
    start = "<!-- rdl:managed policy=managed_prefix -->"
    end = "<!-- /rdl:managed -->"
    if start not in text or end not in text:
        return None
    start_index = text.index(start)
    end_index = text.index(end) + len(end)
    if len(text) > end_index and text[end_index] == "\n":
        end_index += 1
    return text[start_index:end_index]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _optional_non_empty_str(value: Any) -> bool:
    if value is None:
        return False
    return _non_empty_str(value)

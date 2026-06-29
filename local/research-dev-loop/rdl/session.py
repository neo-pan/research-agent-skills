"""Session lifecycle and layout inspection for RDL."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import integrity, store, templates, transition
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

    def state_errors(self) -> tuple[Blocker, ...]:
        if self.state_error is not None:
            return (self.state_error,)
        return _state_value_errors(self)

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
            integrity.validate(self, errors, blockers)

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

    def load_session(self, session_dir: str | Path) -> Session:
        return self._load_session(Path(session_dir))

    def create_session(self, mode: SessionMode | str, mission_file: str | Path, session_id: str) -> Session:
        mode_value = mode.value if isinstance(mode, SessionMode) else str(mode)
        session_dir = self.sessions_root / session_id
        tmp_dir = session_dir.with_name(f"{session_dir.name}.tmp.{os.getpid()}")
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)

        try:
            (tmp_dir / "rounds" / "001").mkdir(parents=True)
            templates.initialize_session_files(tmp_dir, mission_file)
            prompt_objective = Path(mission_file).name
            templates.write_prompt(tmp_dir / "rounds" / "001" / "prompt.md", mode_value, 1, prompt_objective, "none")
            now = transition.now_utc()
            store.write_json_atomic(
                tmp_dir / "state.json",
                {
                    "schema_version": 1,
                    "session_id": session_id,
                    "mode": mode_value,
                    "phase": SessionPhase.PLAN.value,
                    "round": 1,
                    "status": SessionStatus.ACTIVE.value,
                    "mission_file": "mission.md",
                    "guard_session_id": None,
                    "last_guard_command_id": None,
                    "prompt_objective": prompt_objective,
                    "created_at_utc": now,
                    "updated_at_utc": now,
                },
            )
            session = self.load_session(tmp_dir)
            integrity.refresh(session)
            self.sessions_root.mkdir(parents=True, exist_ok=True)
            os.replace(tmp_dir, session_dir)
        except Exception:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
            raise

        return self.load_session(session_dir)

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


def valid_session_id(session_id: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9._-]+", session_id) is not None


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


def _strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _optional_non_empty_str(value: Any) -> bool:
    if value is None:
        return False
    return _non_empty_str(value)

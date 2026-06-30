"""Session lifecycle and layout inspection for RDL."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import integrity, safety, store, templates, transition
from .model import AuditResult, Blocker, SessionMode, SessionPhase, SessionState, SessionStatus


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
        return safety.state_errors(self)

    def audit(self) -> AuditResult:
        return safety.audit(self)


@dataclass(frozen=True)
class SessionLockError(Exception):
    blocker: Blocker


@dataclass
class SessionLock:
    session: Session
    action: str
    acquired: bool = False

    @property
    def path(self) -> Path:
        return self.session.root / ".lock"

    def __enter__(self) -> "SessionLock":
        self.session.root.mkdir(parents=True, exist_ok=True)
        content = f"pid={os.getpid()}\naction={self.action}\ncreated_at_utc={transition.now_utc()}\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(self.path, flags, 0o644)
        except FileExistsError as exc:
            raise SessionLockError(safety.lock_conflict(self.path)) from exc
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        self.acquired = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.acquired and self.path.is_file() and safety.lock_owner_pid(self.path) == os.getpid():
            self.path.unlink()
        self.acquired = False


def acquire_session_lock(session: Session, action: str) -> SessionLock:
    return SessionLock(session, action)


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
            if session.state_errors():
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
    if session_id in {".", ".."}:
        return False
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


def _strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)

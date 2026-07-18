"""Immutable-generation storage for RDL."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from .model import RdlError, canonical_json, validate_loaded_state, validate_session_id


FaultHook = Callable[[str], None]


class Repository:
    """Store complete state generations behind one atomic session pointer."""

    def __init__(self, root: str | Path, fault_hook: FaultHook | None = None):
        self.root = Path(root).resolve()
        self.rdl_root = self.root / ".rdl"
        self.sessions_root = self.rdl_root / "sessions"
        self.store_root = self.rdl_root / ".store"
        self.locks_root = self.rdl_root / "locks"
        self.fault_hook = fault_hook

    @contextmanager
    def start_lock(self) -> Iterator[None]:
        self._durable_mkdir(self.rdl_root)
        self._fsync_dir(self.root)
        with self._lock(self.rdl_root / "start.lock"):
            yield

    @contextmanager
    def session_lock(self, session_id: str) -> Iterator[None]:
        validate_session_id(session_id)
        with self._lock(self.locks_root / f"{session_id}.lock"):
            yield

    def select_session_id(self, requested: str | None) -> str:
        if requested:
            validate_session_id(requested)
            if not self.pointer(requested).is_symlink():
                raise RdlError("session_not_found", f"RDL session not found: {requested}", status="blocked")
            return requested
        active: list[str] = []
        for session_id in self.session_ids():
            try:
                state = self.load(session_id)
            except RdlError:
                continue
            if state.get("status") == "active":
                active.append(session_id)
        if not active:
            raise RdlError("no_active_session", "no active RDL session exists", status="blocked")
        if len(active) > 1:
            raise RdlError("multiple_active_sessions", "multiple active RDL sessions exist", status="blocked")
        return active[0]

    def session_ids(self) -> list[str]:
        if not self.sessions_root.is_dir():
            return []
        return sorted(path.name for path in self.sessions_root.iterdir() if path.is_symlink())

    def active_session_ids(self) -> list[str]:
        result = []
        for session_id in self.session_ids():
            if self.load(session_id).get("status") == "active":
                result.append(session_id)
        return result

    def pointer(self, session_id: str) -> Path:
        return self.sessions_root / session_id

    def generation(self, session_id: str, version: int) -> Path:
        return self.store_root / session_id / str(version)

    def current_generation(self, session_id: str) -> Path:
        pointer = self.pointer(session_id)
        if not pointer.is_symlink():
            raise RdlError("session_not_found", f"RDL session not found: {session_id}", status="blocked")
        try:
            target = pointer.resolve(strict=True)
        except OSError as exc:
            raise RdlError("broken_session_pointer", f"session pointer is broken: {pointer}") from exc
        expected_parent = (self.store_root / session_id).resolve()
        if target.parent != expected_parent:
            raise RdlError("invalid_session_pointer", "session pointer escapes its generation store")
        return target

    def load(self, session_id: str) -> dict[str, Any]:
        generation = self.current_generation(session_id)
        state_path = generation / "state.json"
        try:
            with state_path.open("r", encoding="utf-8") as handle:
                state = json.load(handle)
        except FileNotFoundError as exc:
            raise RdlError("missing_state", "state.json is missing from the current generation") from exc
        except json.JSONDecodeError as exc:
            raise RdlError("invalid_state_json", "state.json is not valid JSON") from exc
        state = validate_loaded_state(state, session_id)
        if generation.name != str(state.get("state_version")):
            raise RdlError("generation_version_mismatch", "generation name does not match state version")
        return state

    def read_views(self, session_id: str) -> dict[str, bytes]:
        generation = self.current_generation(session_id)
        result: dict[str, bytes] = {}
        for path in generation.rglob("*"):
            if path.is_file() and path.name != "state.json":
                result[path.relative_to(generation).as_posix()] = path.read_bytes()
        return result

    def commit(self, session_id: str, state: dict[str, Any], views: dict[str, str]) -> None:
        validate_loaded_state(state, session_id)
        version = int(state["state_version"])
        self._ensure_layout()
        self._fault("after_layout_fsync")
        session_store = self.store_root / session_id
        self._durable_mkdir(session_store)
        self._fault("after_session_store_fsync")
        temp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=session_store))
        final = self.generation(session_id, version)
        if final.exists():
            shutil.rmtree(temp)
            raise RdlError("generation_exists", f"generation already exists: {version}")
        try:
            files = {"state.json": json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", **views}
            for relative, content in sorted(files.items()):
                destination = temp / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("w", encoding="utf-8", newline="\n") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._fault("after_file_fsync")
            self._fsync_tree_dirs(temp)
            self._fault("after_temp_fsync")
            os.replace(temp, final)
            self._fault("after_generation_rename")
            self._fsync_dir(session_store)
            self._fault("after_store_fsync")

            link_temp = self.sessions_root / f".{session_id}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
            relative_target = os.path.relpath(final, self.sessions_root)
            os.symlink(relative_target, link_temp)
            self._fault("after_pointer_create")
            os.replace(link_temp, self.pointer(session_id))
            self._fault("after_pointer_replace")
            self._fsync_dir(self.sessions_root)
            self._fault("after_sessions_fsync")
        except Exception:
            if temp.exists():
                shutil.rmtree(temp)
            for link in self.sessions_root.glob(f".{session_id}.tmp-*"):
                link.unlink(missing_ok=True)
            raise
        try:
            self.cleanup(session_id, version)
        except OSError:
            pass

    def cleanup(self, session_id: str, current_version: int) -> None:
        session_store = self.store_root / session_id
        if not session_store.is_dir():
            return
        keep = {current_version, max(1, current_version - 1)}
        for path in session_store.iterdir():
            if path.name.startswith(".tmp-"):
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_dir() and path.name.isdigit() and int(path.name) not in keep:
                shutil.rmtree(path)

    def discard_uncommitted_start(self, session_id: str) -> None:
        """Remove generations that cannot be committed because no pointer exists."""
        if self.pointer(session_id).is_symlink():
            return
        session_store = self.store_root / session_id
        if session_store.is_dir():
            shutil.rmtree(session_store)

    def generation_diagnostics(self, session_id: str, current_version: int) -> dict[str, list[str]]:
        session_store = self.store_root / session_id
        if not session_store.is_dir():
            return {"temporary": [], "unreferenced": []}
        temporary = sorted(path.name for path in session_store.iterdir() if path.name.startswith(".tmp-"))
        unreferenced = sorted(
            path.name
            for path in session_store.iterdir()
            if path.is_dir() and path.name.isdigit() and int(path.name) not in {current_version, max(1, current_version - 1)}
        )
        return {"temporary": temporary, "unreferenced": unreferenced}

    @contextmanager
    def _lock(self, path: Path) -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _fault(self, point: str) -> None:
        if self.fault_hook is not None:
            self.fault_hook(point)

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _fsync_tree_dirs(self, root: Path) -> None:
        directories = sorted((path for path in root.rglob("*") if path.is_dir()), key=lambda item: len(item.parts), reverse=True)
        for directory in directories:
            self._fsync_dir(directory)
        self._fsync_dir(root)

    def _ensure_layout(self) -> None:
        self._durable_mkdir(self.rdl_root)
        self._durable_mkdir(self.store_root)
        self._durable_mkdir(self.sessions_root)

    def _durable_mkdir(self, path: Path) -> None:
        if path.is_dir():
            return
        parent = path.parent
        if not parent.is_dir():
            self._durable_mkdir(parent)
        try:
            path.mkdir()
        except FileExistsError:
            if not path.is_dir():
                raise
        self._fsync_dir(parent)


def compact_json(value: Any) -> str:
    return canonical_json(value) + "\n"

#!/usr/bin/env python3

from __future__ import annotations

import argparse
import errno
import fcntl
import os
import stat
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


COMMAND_NAME = "rdl"
SYSTEM_BIN_DIRS = {
    Path(path).resolve()
    for path in (
        "/bin",
        "/sbin",
        "/usr/bin",
        "/usr/sbin",
        "/usr/local/bin",
        "/usr/local/sbin",
    )
}


class InstallerError(Exception):
    def __init__(self, message: str, *, blocked: bool = False):
        super().__init__(message)
        self.blocked = blocked


@dataclass(frozen=True)
class TargetState:
    status: str
    link_target: str | None = None


@dataclass(frozen=True)
class PathState:
    entries: tuple[Path, ...]
    unsafe: bool


def canonical_source() -> Path:
    return Path(__file__).resolve().parents[1] / "local" / "research-dev-loop" / "bin" / COMMAND_NAME


def bin_directory(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise InstallerError("--bin-dir must be an absolute path")
    try:
        return path.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise InstallerError(f"Cannot resolve command directory {path}: {exc}") from exc


def path_state(raw: str) -> PathState:
    entries: list[Path] = []
    unsafe = False
    for item in raw.split(os.pathsep):
        path = Path(item) if item else None
        if path is None or not path.is_absolute():
            unsafe = True
            continue
        try:
            entries.append(path.resolve(strict=False))
        except (OSError, RuntimeError):
            unsafe = True
    return PathState(tuple(entries), unsafe)


def inspect_target(target: Path, source: Path) -> TargetState:
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return TargetState("absent")
    if not stat.S_ISLNK(metadata.st_mode):
        return TargetState("directory" if stat.S_ISDIR(metadata.st_mode) else "file")
    link_target = os.readlink(target)
    if link_target == str(source):
        return TargetState("current", link_target)
    try:
        target.stat()
    except (FileNotFoundError, RuntimeError):
        return TargetState("broken", link_target)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return TargetState("broken", link_target)
        raise
    return TargetState("symlink", link_target)


def inspect_at(directory_fd: int, source: Path) -> TargetState:
    try:
        metadata = os.stat(COMMAND_NAME, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return TargetState("absent")
    if not stat.S_ISLNK(metadata.st_mode):
        return TargetState("directory" if stat.S_ISDIR(metadata.st_mode) else "file")
    link_target = os.readlink(COMMAND_NAME, dir_fd=directory_fd)
    if link_target == str(source):
        return TargetState("current", link_target)
    try:
        os.stat(COMMAND_NAME, dir_fd=directory_fd, follow_symlinks=True)
    except FileNotFoundError:
        return TargetState("broken", link_target)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return TargetState("broken", link_target)
        raise
    return TargetState("symlink", link_target)


def executable_shadow(entries: tuple[Path, ...], bin_dir: Path) -> Path | None:
    try:
        target_index = entries.index(bin_dir)
    except ValueError:
        return None
    for directory in entries[:target_index]:
        candidate = directory / COMMAND_NAME
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
        except (OSError, RuntimeError):
            continue
    return None


def validate_source(source: Path) -> None:
    if not source.is_file() or not os.access(source, os.X_OK):
        raise InstallerError(f"Canonical RDL launcher is missing or not executable: {source}")


def validate_mutation_directory(bin_dir: Path) -> os.stat_result:
    if os.name != "posix":
        raise InstallerError("RDL command installation requires a Unix-like environment", blocked=True)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise InstallerError("Refusing to install or uninstall commands as root", blocked=True)
    if bin_dir in SYSTEM_BIN_DIRS:
        raise InstallerError(f"Refusing to manage a system command directory: {bin_dir}", blocked=True)
    try:
        home = Path.home().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InstallerError(f"Cannot resolve HOME: {exc}", blocked=True) from exc
    if bin_dir == home or not bin_dir.is_relative_to(home):
        raise InstallerError(f"Command directory must be inside HOME: {bin_dir}", blocked=True)
    try:
        metadata = bin_dir.stat()
    except OSError as exc:
        raise InstallerError(f"Command directory is unavailable: {bin_dir}: {exc}", blocked=True) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise InstallerError(f"Command directory is not a directory: {bin_dir}", blocked=True)
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise InstallerError(f"Command directory is not owned by the current user: {bin_dir}", blocked=True)
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise InstallerError(f"Command directory is group- or world-writable: {bin_dir}", blocked=True)
    if not os.access(bin_dir, os.W_OK | os.X_OK):
        raise InstallerError(f"Command directory is not writable: {bin_dir}", blocked=True)
    return metadata


@contextmanager
def locked_directory(bin_dir: Path) -> Iterator[int]:
    expected = validate_mutation_directory(bin_dir)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        directory_fd = os.open(bin_dir, flags)
    except OSError as exc:
        raise InstallerError(f"Cannot open command directory {bin_dir}: {exc}", blocked=True) from exc
    try:
        actual = os.fstat(directory_fd)
        if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
            raise InstallerError(f"Command directory changed while opening it: {bin_dir}", blocked=True)
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        yield directory_fd
    finally:
        os.close(directory_fd)


def status(bin_dir: Path, source: Path, paths: PathState) -> int:
    target = bin_dir / COMMAND_NAME
    state = inspect_target(target, source)
    on_path = bin_dir in paths.entries
    shadow = executable_shadow(paths.entries, bin_dir) if on_path else None
    details = [
        f"target={target}",
        f"state={state.status}",
        f"on_path={'yes' if on_path else 'no'}",
        f"path={'unsafe' if paths.unsafe else 'safe'}",
        f"shadowed_by={shadow if shadow else 'none'}",
        f"source_available={'yes' if source.is_file() and os.access(source, os.X_OK) else 'no'}",
    ]
    if state.link_target is not None:
        details.append(f"link_target={state.link_target}")
    print("RDL command status: " + "; ".join(details))
    return 0


def install(bin_dir: Path, source: Path, paths: PathState) -> int:
    validate_source(source)
    if paths.unsafe:
        raise InstallerError("PATH contains an empty, relative, or unresolvable entry")
    if bin_dir not in paths.entries:
        raise InstallerError(f"Command directory is not on PATH: {bin_dir}", blocked=True)
    shadow = executable_shadow(paths.entries, bin_dir)
    if shadow is not None:
        raise InstallerError(f"An earlier executable shadows rdl: {shadow}", blocked=True)
    target = bin_dir / COMMAND_NAME
    with locked_directory(bin_dir) as directory_fd:
        state = inspect_at(directory_fd, source)
        if state.status == "current":
            print(f"RDL command unchanged: {target} -> {source}")
            return 0
        if state.status != "absent":
            raise InstallerError(f"Refusing to replace {state.status} target: {target}", blocked=True)
        try:
            os.symlink(str(source), COMMAND_NAME, dir_fd=directory_fd)
        except FileExistsError:
            state = inspect_at(directory_fd, source)
            if state.status == "current":
                print(f"RDL command unchanged: {target} -> {source}")
                return 0
            raise InstallerError(f"Refusing to replace {state.status} target: {target}", blocked=True)
    print(f"RDL command installed: {target} -> {source}")
    return 0


def uninstall(bin_dir: Path, source: Path) -> int:
    target = bin_dir / COMMAND_NAME
    with locked_directory(bin_dir) as directory_fd:
        state = inspect_at(directory_fd, source)
        if state.status == "absent":
            print(f"RDL command absent: {target}")
            return 0
        if state.status != "current":
            raise InstallerError(f"Refusing to remove {state.status} target: {target}", blocked=True)
        final_state = inspect_at(directory_fd, source)
        if final_state.status != "current":
            raise InstallerError(f"RDL command target changed before removal: {target}", blocked=True)
        os.unlink(COMMAND_NAME, dir_fd=directory_fd)
    print(f"RDL command uninstalled: {target}")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Manage the optional RDL command adapter.")
    result.add_argument("action", choices=("install", "status", "uninstall"))
    result.add_argument("--bin-dir", required=True, help="Existing user-owned command directory")
    return result


def run(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    source = canonical_source()
    bin_dir = bin_directory(args.bin_dir)
    paths = path_state(os.environ.get("PATH", ""))
    if args.action == "status":
        return status(bin_dir, source, paths)
    if args.action == "install":
        return install(bin_dir, source, paths)
    return uninstall(bin_dir, source)


def main() -> int:
    if sys.version_info < (3, 9):
        print("error: RDL command installation requires Python 3.9 or newer", file=sys.stderr)
        return 1
    try:
        return run()
    except InstallerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2 if exc.blocked else 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

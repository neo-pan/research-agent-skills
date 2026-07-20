"""Ownership-aware installation of repository-managed symbolic links."""

from __future__ import annotations

import errno
import fcntl
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, Sequence


class ManagedLinkError(Exception):
    """A safe managed-link plan cannot be completed."""


@dataclass(frozen=True)
class LinkState:
    kind: str
    ownership: str | None = None
    health: str | None = None
    link_target: str | None = None

    @property
    def status(self) -> str:
        """Compatibility status for adapters that expose a single state word."""

        if self.kind != "symlink":
            return self.kind
        if self.ownership == "expected":
            return "current"
        if self.health == "broken":
            return "broken"
        return "symlink"

    def summary(self) -> str:
        fields = [f"kind={self.kind}"]
        if self.ownership is not None:
            fields.append(f"ownership={self.ownership}")
        if self.health is not None:
            fields.append(f"health={self.health}")
        if self.link_target is not None:
            fields.append(f"link_target={self.link_target}")
        return "; ".join(fields)


@dataclass(frozen=True)
class LinkAction:
    action: str
    name: str
    source: Path | None
    state: LinkState


@dataclass(frozen=True)
class BatchResult:
    desired: int
    created: int
    replaced: int
    unchanged: int
    pruned: int


def inspect_link(target: Path, expected: Path | None, owned_roots: Sequence[Path]) -> LinkState:
    """Classify one target without mutating it."""

    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return LinkState("absent")
    if not stat.S_ISLNK(metadata.st_mode):
        return LinkState("directory" if stat.S_ISDIR(metadata.st_mode) else "file")

    raw_target = os.readlink(target)
    health = _link_health(target)
    expected_text = str(expected) if expected is not None else None
    if expected_text is not None and raw_target == expected_text:
        ownership = "expected"
    elif _owned_absolute_target(raw_target, owned_roots):
        ownership = "current-checkout"
    else:
        ownership = "foreign"
    return LinkState("symlink", ownership, health, raw_target)


def inspect_link_at(
    directory_fd: int,
    name: str,
    expected: Path | None,
    owned_roots: Sequence[Path],
) -> LinkState:
    """Classify one target relative to an already-open directory."""

    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return LinkState("absent")
    if not stat.S_ISLNK(metadata.st_mode):
        return LinkState("directory" if stat.S_ISDIR(metadata.st_mode) else "file")

    raw_target = os.readlink(name, dir_fd=directory_fd)
    health = _link_health_at(directory_fd, name)
    expected_text = str(expected) if expected is not None else None
    if expected_text is not None and raw_target == expected_text:
        ownership = "expected"
    elif _owned_absolute_target(raw_target, owned_roots):
        ownership = "current-checkout"
    else:
        ownership = "foreign"
    return LinkState("symlink", ownership, health, raw_target)


def install_batch(
    target_dir: Path,
    desired: Mapping[str, Path],
    owned_roots: Sequence[Path],
) -> BatchResult:
    """Install a complete desired set after a conflict-free batch preflight."""

    normalized_desired = {name: source.resolve(strict=True) for name, source in desired.items()}
    normalized_roots = tuple(root.resolve(strict=False) for root in owned_roots)
    target_dir.mkdir(parents=True, exist_ok=True)
    with _locked_directory(target_dir) as directory_fd:
        actions = _plan_at(directory_fd, normalized_desired, normalized_roots)
        conflicts = [item for item in actions if item.action == "block"]
        if conflicts:
            details = "\n".join(
                f"conflict: target={target_dir / item.name}; {item.state.summary()}"
                for item in conflicts
            )
            raise ManagedLinkError(
                details
                + "\nremediation: move or remove each conflicting target explicitly, then retry"
            )

        counts = {"create": 0, "replace-managed": 0, "unchanged": 0, "prune-managed": 0}
        for item in actions:
            if item.action == "unchanged":
                counts[item.action] += 1
            elif item.action == "create":
                _require_planned_state(directory_fd, item, normalized_roots)
                _create_link(directory_fd, item, normalized_roots, target_dir)
                counts[item.action] += 1
            elif item.action == "replace-managed":
                _require_planned_state(directory_fd, item, normalized_roots)
                os.unlink(item.name, dir_fd=directory_fd)
                _create_link(directory_fd, item, normalized_roots, target_dir)
                counts[item.action] += 1
            elif item.action == "prune-managed":
                _require_planned_state(directory_fd, item, normalized_roots)
                os.unlink(item.name, dir_fd=directory_fd)
                counts[item.action] += 1

    return BatchResult(
        desired=len(normalized_desired),
        created=counts["create"],
        replaced=counts["replace-managed"],
        unchanged=counts["unchanged"],
        pruned=counts["prune-managed"],
    )


def _plan_at(
    directory_fd: int,
    desired: Mapping[str, Path],
    owned_roots: Sequence[Path],
) -> list[LinkAction]:
    actions: list[LinkAction] = []
    for name, source in sorted(desired.items()):
        state = inspect_link_at(directory_fd, name, source, owned_roots)
        if state.kind == "absent":
            action = "create"
        elif state.kind == "symlink" and state.ownership == "expected" and state.health == "valid":
            action = "unchanged"
        elif state.kind == "symlink" and state.ownership == "current-checkout":
            action = "replace-managed"
        else:
            action = "block"
        actions.append(LinkAction(action, name, source, state))

    desired_names = set(desired)
    for name in sorted(os.listdir(directory_fd)):
        if name in desired_names:
            continue
        state = inspect_link_at(directory_fd, name, None, owned_roots)
        if state.kind == "symlink" and state.ownership == "current-checkout":
            actions.append(LinkAction("prune-managed", name, None, state))
    return actions


def _require_planned_state(
    directory_fd: int,
    item: LinkAction,
    owned_roots: Sequence[Path],
) -> None:
    current = inspect_link_at(directory_fd, item.name, item.source, owned_roots)
    if current != item.state:
        raise ManagedLinkError(
            f"target changed after preflight: name={item.name}; "
            f"planned=({item.state.summary()}); current=({current.summary()})"
        )


def _create_link(
    directory_fd: int,
    item: LinkAction,
    owned_roots: Sequence[Path],
    target_dir: Path,
) -> None:
    if item.source is None:
        raise ManagedLinkError(f"missing source for managed link: {item.name}")
    try:
        os.symlink(str(item.source), item.name, dir_fd=directory_fd)
    except FileExistsError as exc:
        current = inspect_link_at(directory_fd, item.name, item.source, owned_roots)
        raise ManagedLinkError(
            f"target changed while creating link: target={target_dir / item.name}; "
            f"{current.summary()}"
        ) from exc


def _link_health(target: Path) -> str:
    try:
        target.stat()
    except (FileNotFoundError, RuntimeError):
        return "broken"
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return "broken"
        raise
    return "valid"


def _link_health_at(directory_fd: int, name: str) -> str:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=True)
    except (FileNotFoundError, RuntimeError):
        return "broken"
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            return "broken"
        raise
    return "valid"


def _owned_absolute_target(raw_target: str, owned_roots: Sequence[Path]) -> bool:
    candidate = Path(raw_target)
    if not candidate.is_absolute():
        return False
    normalized = Path(os.path.normpath(raw_target))
    return any(normalized == root or normalized.is_relative_to(root) for root in owned_roots)


@contextmanager
def _locked_directory(target_dir: Path) -> Iterator[int]:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(target_dir, flags)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield descriptor
    finally:
        os.close(descriptor)

"""Conservative repair planning and execution for RDL sessions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import integrity, store, templates
from .model import Blocker
from .protocol import descriptor
from .session import Session


@dataclass(frozen=True)
class RepairResult:
    repaired: tuple[str, ...]
    errors: tuple[Blocker, ...]
    blockers: tuple[Blocker, ...]

    @property
    def ok(self) -> bool:
        return not self.errors and not self.blockers


def repair(session: Session) -> RepairResult:
    repaired: list[str] = []
    blockers: list[Blocker] = []

    _repair_stale_lock(session.root / ".lock", repaired, blockers)
    if blockers:
        return RepairResult(tuple(repaired), (), tuple(blockers))

    errors, blockers = validate_scope(session)
    if errors or blockers:
        return RepairResult(tuple(repaired), tuple(errors), tuple(blockers))

    prompt_blockers = _repair_initial_prompt(session, repaired)
    if prompt_blockers:
        return RepairResult(tuple(repaired), (), tuple(prompt_blockers))

    integrity.refresh(session)
    repaired.append("integrity.json")
    return RepairResult(tuple(repaired), (), ())


def validate_scope(session: Session) -> tuple[list[Blocker], list[Blocker]]:
    errors: list[Blocker] = []
    blockers: list[Blocker] = []
    _validate_structure(session, errors, blockers)
    if errors or blockers:
        return errors, blockers

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
        return errors, blockers

    _validate_manifest_completeness(session, manifest, errors)
    _validate_existing_entries(session, manifest, errors)
    return errors, blockers


def _repair_stale_lock(path: Path, repaired: list[str], blockers: list[Blocker]) -> None:
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
                "RDL session lock is held by another running process.",
                "Wait for the current RDL command to finish.",
            )
        )
        return
    path.unlink()
    repaired.append(".lock")


def _validate_structure(session: Session, errors: list[Blocker], blockers: list[Blocker]) -> None:
    if session.state_error is not None:
        errors.append(session.state_error)
        return
    audit = session.audit()
    for error in audit.errors:
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

    for blocker in audit.blockers:
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


def _validate_manifest_completeness(session: Session, manifest: dict[str, Any], errors: list[Blocker]) -> None:
    expected_policy = integrity.expected_policies(session)
    seen: dict[str, int] = {}
    for entry in manifest["entries"]:
        relative = entry["path"]
        seen[relative] = seen.get(relative, 0) + 1
        if not descriptor.path_known(relative):
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


def _validate_state_derived_history(session: Session, seen: dict[str, int], errors: list[Blocker]) -> None:
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


def _validate_existing_entries(session: Session, manifest: dict[str, Any], errors: list[Blocker]) -> None:
    active_prompt = f"rounds/{session.state.round:03d}/prompt.md"
    for entry in manifest["entries"]:
        relative = entry["path"]
        if not descriptor.path_known(relative):
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


def _repair_initial_prompt(session: Session, repaired: list[str]) -> list[Blocker]:
    prompt_relative = f"rounds/{session.state.round:03d}/prompt.md"
    prompt_path = session.root / prompt_relative
    if prompt_path.is_file():
        return []
    if session.state.round != 1:
        return [
            Blocker(
                "unsafe_missing_prompt",
                prompt_relative,
                "Only the initial round prompt can be deterministically repaired.",
                f"Restore {prompt_relative} from a known-good source.",
            )
        ]
    if not session.state.prompt_objective:
        return [
            Blocker(
                "missing_prompt_metadata",
                prompt_relative,
                "Initial prompt cannot be deterministically repaired without prompt_objective metadata.",
                f"Restore {prompt_relative} or start a new session with prompt metadata.",
            )
        ]
    templates.write_prompt(prompt_path, session.state.mode, 1, session.state.prompt_objective, "none")
    repaired.append(prompt_relative)
    return []


def _unsafe(code: str, relative: str, message: str) -> Blocker:
    return Blocker(code, relative, message, f"Restore {relative} from a known-good source before repair.")


def _lock_owner_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not text:
        return None
    line = text[0].strip()
    if not line.startswith("pid="):
        return None
    try:
        return int(line.removeprefix("pid="))
    except ValueError:
        return None


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

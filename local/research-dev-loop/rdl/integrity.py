"""Integrity manifest generation and validation for RDL sessions."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import store
from .model import Blocker
from .protocol import descriptor


def refresh(session: Any) -> None:
    entries = [_manifest_entry(session.root / relative, relative) for relative in existing_protocol_files(session)]
    store.write_json_atomic(
        session.root / "integrity.json",
        {
            "schema_version": 1,
            "session_id": session.state.session_id,
            "entries": entries,
        },
    )


def validate(session: Any, errors: list[Blocker], blockers: list[Blocker]) -> None:
    path = session.root / "integrity.json"
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

    expected_policy = expected_policies(session)
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
        if not session_path_known(session, relative):
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


def protocol_files(session: Any) -> tuple[str, ...]:
    paths = list(_session_protocol_files(session))

    paths.extend(_state_required_round_files(session))
    paths.extend(_existing_round_files(session))
    return tuple(dict.fromkeys(relative for relative in paths if relative))


def existing_protocol_files(session: Any) -> tuple[str, ...]:
    return tuple(relative for relative in protocol_files(session) if (session.root / relative).is_file())


def expected_policies(session: Any) -> dict[str, str]:
    return {relative: descriptor.policy_for_path(relative) for relative in protocol_files(session)}


def session_path_known(session: Any, relative: str) -> bool:
    if relative == session.state.mission_file:
        return descriptor.path_policy(relative) is not None or _safe_state_mission_path(relative)
    return descriptor.path_known(relative)


def _session_protocol_files(session: Any) -> list[str]:
    paths: list[str] = []
    for relative in descriptor.required_session_files():
        if relative == "mission.md":
            paths.append(session.state.mission_file)
        else:
            paths.append(relative)
    for relative in descriptor.optional_session_files():
        if (session.root / relative).is_file():
            paths.append(relative)
    return paths


def managed_block(text: str) -> str | None:
    start = "<!-- rdl:managed policy=managed_prefix -->"
    end = "<!-- /rdl:managed -->"
    if text.count(start) != 1 or text.count(end) != 1:
        return None
    start_index = text.index(start)
    end_index = text.index(end) + len(end)
    if end_index <= start_index + len(start):
        return None
    if len(text) > end_index and text[end_index] == "\n":
        end_index += 1
    return text[start_index:end_index]


def _manifest_entry(path: Path, relative: str) -> dict[str, object]:
    policy = descriptor.policy_for_path(relative)
    data = path.read_bytes()
    entry: dict[str, object] = {
        "path": relative,
        "policy": policy,
        "sha256": _sha256(data),
    }
    if policy == "append_only":
        entry["size"] = len(data)
        entry["prefix_sha256"] = entry["sha256"]
    elif policy == "managed_prefix":
        block = managed_block(path.read_text(encoding="utf-8"))
        if block is None:
            raise ValueError(f"managed-prefix file is missing managed block: {relative}")
        entry["managed_sha256"] = _sha256(block.encode("utf-8"))
    return entry


def _state_required_round_files(session: Any) -> list[str]:
    paths: list[str] = []
    if getattr(session.state, "round", 0) < 1:
        return paths
    for round_number in range(1, session.state.round + 1):
        round_prefix = f"rounds/{round_number:03d}"
        for file_name in descriptor.completed_round_files(session.state.mode):
            relative = f"{round_prefix}/{file_name}"
            if (session.root / relative).is_file():
                paths.append(relative)
            elif descriptor.policy_for_path(relative) in {"cli_owned", "append_only", "managed_prefix"}:
                paths.append(relative)
    return paths


def _existing_round_files(session: Any) -> list[str]:
    paths: list[str] = []
    rounds_dir = session.root / "rounds"
    if not rounds_dir.is_dir():
        return paths
    for round_dir in sorted(path for path in rounds_dir.iterdir() if path.is_dir()):
        for file_name in descriptor.round_file_names():
            path = round_dir / file_name
            relative = str(path.relative_to(session.root))
            if path.is_file() and descriptor.path_known(relative):
                paths.append(relative)
    return paths


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


def manifest_shape_valid(data: Any) -> bool:
    return _integrity_shape_valid(data)


def file_sha256(path: Path) -> str:
    return _sha256(path.read_bytes())


def bytes_sha256(data: bytes) -> str:
    return _sha256(data)


def _safe_state_mission_path(relative: str) -> bool:
    if relative in {"", ".", ".."}:
        return False
    if relative.startswith("/") or relative.startswith("./") or relative.startswith("../"):
        return False
    parts = relative.split("/")
    return "." not in parts and ".." not in parts


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
        block = managed_block(path.read_text(encoding="utf-8"))
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


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)

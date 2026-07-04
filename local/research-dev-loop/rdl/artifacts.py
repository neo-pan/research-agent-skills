"""Read-only evidence artifact integrity checks for RDL gates."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import store

if TYPE_CHECKING:
    from .session import Session


_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ArtifactFinding:
    severity: str
    code: str
    location: str
    message: str
    next_action: str


@dataclass(frozen=True)
class ArtifactReport:
    artifact_status: str
    checked_paths: int
    remote_artifacts: int
    findings: tuple[ArtifactFinding, ...]

    def details(self) -> dict[str, object]:
        return {
            "artifact_status": self.artifact_status,
            "checked_paths": self.checked_paths,
            "remote_artifacts": self.remote_artifacts,
            "findings": [
                {
                    "severity": finding.severity,
                    "code": finding.code,
                    "location": finding.location,
                    "message": finding.message,
                    "next_action": finding.next_action,
                }
                for finding in self.findings
            ],
        }


@dataclass(frozen=True)
class _ArtifactEntry:
    artifact_id: str
    raw_path: str
    resolved_path: Path
    size: int | None
    sha256: str | None


def check(session: "Session") -> ArtifactReport:
    manifest_file = session.root / "artifact-manifest.json"
    try:
        manifest = store.read_json(manifest_file)
    except (FileNotFoundError, json.JSONDecodeError):
        return ArtifactReport("not_available", 0, 0, ())
    if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), list):
        return ArtifactReport("not_available", 0, 0, ())

    entries: list[_ArtifactEntry] = []
    remote_count = 0
    for artifact in manifest["artifacts"]:
        if not isinstance(artifact, dict):
            continue
        raw_path = artifact.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            if isinstance(artifact.get("url"), str) and artifact["url"].strip():
                remote_count += 1
            continue
        entries.append(
            _ArtifactEntry(
                artifact_id=str(artifact.get("id") or "unknown"),
                raw_path=raw_path.strip(),
                resolved_path=_resolve_artifact_path(session, raw_path.strip()),
                size=artifact["size"] if _strict_int(artifact.get("size")) and artifact["size"] >= 0 else None,
                sha256=artifact["sha256"] if isinstance(artifact.get("sha256"), str) and _DIGEST_RE.fullmatch(artifact["sha256"]) else None,
            )
        )

    findings: list[ArtifactFinding] = []
    missing_paths = {entry.raw_path for entry in entries if not entry.resolved_path.is_file()}
    for entry in entries:
        if entry.raw_path in missing_paths:
            findings.append(
                ArtifactFinding(
                    "blocking",
                    "missing_artifact_path",
                    _location(entry.artifact_id),
                    f"Artifact {entry.artifact_id} records a local path that is not reachable.",
                    "Restore the local artifact file or update artifact-manifest.json.",
                )
            )

    duplicate_hash_paths = _duplicate_hash_paths(entries, missing_paths)
    for raw_path, artifact_ids in duplicate_hash_paths.items():
        findings.append(
            ArtifactFinding(
                "warning",
                "duplicate_artifact_path_hashes",
                "artifact-manifest.json",
                f"Multiple artifact records share one reachable local path with different recorded hashes: {', '.join(artifact_ids)}.",
                "Use distinct artifact paths for versioned snapshots or document the intentional reuse.",
            )
        )

    for entry in entries:
        if entry.raw_path in missing_paths or entry.raw_path in duplicate_hash_paths:
            continue
        if entry.size is not None and entry.resolved_path.stat().st_size != entry.size:
            findings.append(
                ArtifactFinding(
                    "blocking",
                    "artifact_size_mismatch",
                    _location(entry.artifact_id),
                    f"Artifact {entry.artifact_id} byte size does not match artifact-manifest.json.",
                    "Regenerate the artifact, or update its recorded size after verifying the change.",
                )
            )
        if entry.sha256 is not None and _sha256(entry.resolved_path) != entry.sha256:
            findings.append(
                ArtifactFinding(
                    "blocking",
                    "artifact_sha256_mismatch",
                    _location(entry.artifact_id),
                    f"Artifact {entry.artifact_id} sha256 does not match artifact-manifest.json.",
                    "Regenerate the artifact, or update its recorded sha256 after verifying the change.",
                )
            )

    if any(finding.severity == "blocking" for finding in findings):
        status = "blocked"
    elif findings:
        status = "needs_attention"
    else:
        status = "ok"
    return ArtifactReport(status, len(entries), remote_count, tuple(findings))


def _resolve_artifact_path(session: "Session", raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return _repo_root(session) / path


def _repo_root(session: "Session") -> Path:
    if session.root.parent.name == "sessions" and session.root.parent.parent.name == ".rdl":
        return session.root.parent.parent.parent
    return session.root


def _duplicate_hash_paths(entries: list[_ArtifactEntry], missing_paths: set[str]) -> dict[str, list[str]]:
    by_path: dict[str, list[_ArtifactEntry]] = {}
    for entry in entries:
        if entry.raw_path in missing_paths or entry.sha256 is None:
            continue
        by_path.setdefault(entry.raw_path, []).append(entry)
    return {
        raw_path: sorted(entry.artifact_id for entry in path_entries)
        for raw_path, path_entries in by_path.items()
        if len({entry.sha256 for entry in path_entries}) > 1
    }


def _location(artifact_id: str) -> str:
    return f"artifact-manifest.json#{artifact_id}"


def _strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

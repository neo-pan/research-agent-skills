"""Structured RDL record writers for small protocol-shaped edits."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING
from urllib.parse import urlparse

from . import documents, store
from .model import Blocker
from .protocol import descriptor

if TYPE_CHECKING:
    from .session import Session


@dataclass(frozen=True)
class RecordResult:
    updated_file: str
    record_kind: str
    record_id: str = ""

    def details(self) -> dict[str, object]:
        result = {
            "updated_file": self.updated_file,
            "record_kind": self.record_kind,
        }
        if self.record_id:
            result["record_id"] = self.record_id
        return result


def record_artifact(session: "Session", values: tuple[str, ...]) -> tuple[RecordResult | None, tuple[Blocker, ...]]:
    if len(values) != 4:
        return None, (_usage_blocker("artifact", "rdl record artifact <id> <kind> <path-or-url> <description>"),)
    artifact_id, kind, location, description = (_clean_text(value) for value in values)
    blockers = _required_values(
        (
            (artifact_id, "artifact id"),
            (kind, "artifact kind"),
            (location, "artifact path or URL"),
            (description, "artifact description"),
        )
    )
    if artifact_id and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", artifact_id) is None:
        blockers.append(
            Blocker(
                "invalid_artifact_id",
                "",
                "artifact id must start with a letter and contain only letters, numbers, dot, underscore, and dash.",
                "Use rdl record artifact <id> <kind> <path-or-url> <description>.",
            )
        )
    manifest_path = session.root / "artifact-manifest.json"
    manifest = _read_manifest(manifest_path)
    if isinstance(manifest, Blocker):
        blockers.append(manifest)
    elif _artifact_id_exists(manifest, artifact_id):
        blockers.append(
            Blocker(
                "duplicate_artifact_id",
                "artifact-manifest.json",
                f"artifact id already exists: {artifact_id}",
                "Choose a new artifact id or edit artifact-manifest.json intentionally.",
            )
        )
    if _remote_url(location):
        resolved = None
    else:
        resolved = _repo_root(session) / location
        if location and not resolved.is_file():
            blockers.append(
                Blocker(
                    "missing_artifact_path",
                    location,
                    "artifact path is not a reachable local file.",
                    "Create the artifact file or pass an http(s) URL.",
                )
            )
    if blockers:
        return None, tuple(blockers)

    assert isinstance(manifest, dict)
    artifact = {
        "id": artifact_id,
        "kind": kind,
        "round": session.state.round,
        "description": description,
    }
    if resolved is None:
        artifact["url"] = location
    else:
        artifact["path"] = location
        artifact["size"] = resolved.stat().st_size
        artifact["sha256"] = _sha256(resolved)
    manifest["artifacts"].append(artifact)
    store.write_json_atomic(manifest_path, manifest)
    return RecordResult("artifact-manifest.json", "artifact", artifact_id), ()


def record_finding(session: "Session", values: tuple[str, ...]) -> tuple[RecordResult | None, tuple[Blocker, ...]]:
    if len(values) != 5:
        return None, (_usage_blocker("finding", "rdl record finding <severity> <category> <location> <claim> <required-resolution>"),)
    severity, category, location, claim, resolution = (_clean_cell(value) for value in values)
    blockers = _required_values(
        (
            (severity, "finding severity"),
            (category, "finding category"),
            (location, "finding location"),
            (claim, "finding claim"),
            (resolution, "finding required resolution"),
        )
    )
    if severity and not descriptor.value_allowed("finding-severity", severity):
        blockers.append(
            Blocker(
                "invalid_review_finding_severity",
                "",
                "Review finding severity is unsupported.",
                "Use blocking, warning, or note.",
            )
        )
    if category and not descriptor.value_allowed("finding-category", category):
        blockers.append(
            Blocker(
                "invalid_review_finding_category",
                "",
                "Review finding category is unsupported.",
                "Use evidence, overclaim, staleness, handoff, memory, artifact, or decision.",
            )
        )
    review_path = session.round_dir() / "review.md"
    if not review_path.is_file():
        blockers.append(
            Blocker(
                "missing_review",
                str(review_path),
                "review.md is missing.",
                "Run rdl review before recording review findings.",
            )
        )
    else:
        section = documents.section(review_path, "Returned Review Findings")
        if section.start_line is None:
            blockers.append(
                Blocker(
                    "missing_review_section",
                    f"{review_path}#Returned Review Findings",
                    "Returned Review Findings section is missing.",
                    "Restore the review.md template before recording findings.",
                )
            )
        else:
            blockers.extend(_review_finding_shape_blockers(review_path))
    if blockers:
        return None, tuple(blockers)

    line = f"- {severity} | {category} | {location} | {claim} | {resolution}"
    rendered = _append_section_line(store.read_text(review_path), "Returned Review Findings", line)
    store.write_text_atomic(review_path, rendered)
    return RecordResult("rounds/%03d/review.md" % session.state.round, "finding"), ()


def _usage_blocker(kind: str, usage: str) -> Blocker:
    return Blocker(
        "invalid_record_arguments",
        "",
        f"record {kind} arguments are incomplete.",
        usage,
    )


def _required_values(values: tuple[tuple[str, str], ...]) -> list[Blocker]:
    blockers: list[Blocker] = []
    for value, label in values:
        if not _meaningful(value):
            blockers.append(
                Blocker(
                    "missing_record_value",
                    "",
                    f"{label} requires a non-placeholder value.",
                    "Pass concrete record values.",
                )
            )
    return blockers


def _read_manifest(path: Path) -> dict[str, Any] | Blocker:
    try:
        manifest = store.read_json(path)
    except Exception as exc:
        return Blocker(
            "invalid_artifact_manifest",
            "artifact-manifest.json",
            f"artifact manifest cannot be read: {exc}",
            "Restore artifact-manifest.json before recording artifacts.",
        )
    if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), list):
        return Blocker(
            "invalid_artifact_manifest",
            "artifact-manifest.json",
            "artifact manifest must contain an artifacts list.",
            "Restore artifact-manifest.json before recording artifacts.",
        )
    return manifest


def _artifact_id_exists(manifest: dict[str, Any], artifact_id: str) -> bool:
    return any(isinstance(item, dict) and item.get("id") == artifact_id for item in manifest.get("artifacts", ()))


def _review_finding_shape_blockers(path: Path) -> list[Blocker]:
    return [
        blocker
        for blocker in documents.validate("review", path)
        if blocker.code.startswith("invalid_review_finding")
    ]


def _append_section_line(text: str, heading: str, line: str) -> str:
    lines = text.splitlines()
    start, end = _section_bounds(lines, heading)
    content = [value.strip() for value in lines[start:end] if value.strip()]
    if len(content) == 1 and content[0].lower() in {"none", "none recorded", "- none"}:
        lines[start:end] = ["", line, ""]
        return "\n".join(lines).rstrip() + "\n"

    insert_at = end
    while insert_at > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, line)
    return "\n".join(lines).rstrip() + "\n"


def _section_bounds(lines: list[str], heading: str) -> tuple[int, int]:
    heading_re = re.compile(rf"^[ \t]*##[ \t]+{re.escape(heading)}[ \t]*$")
    start = None
    for index, line in enumerate(lines):
        if heading_re.match(line):
            start = index + 1
            break
    if start is None:
        raise ValueError(f"missing section: {heading}")
    end = len(lines)
    for index in range(start, len(lines)):
        if re.match(r"^[ \t]*##[ \t]+", lines[index]):
            end = index
            break
    return start, end


def _repo_root(session: "Session") -> Path:
    if session.root.parent.name == "sessions" and session.root.parent.parent.name == ".rdl":
        return session.root.parent.parent.parent
    return session.root


def _remote_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _clean_cell(value: str) -> str:
    return _clean_text(value).replace("|", "/")


def _clean_text(value: str) -> str:
    return " ".join(value.strip().split())


def _meaningful(value: str) -> bool:
    normalized = value.strip().lower()
    return bool(normalized and normalized not in {"-", "...", "tbd", "todo", "n/a", "not applicable", "none recorded"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

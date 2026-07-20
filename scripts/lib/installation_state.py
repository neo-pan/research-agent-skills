"""Read-only Codex installation-state reporting for this repository."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .managed_links import LinkState, inspect_link
from .repository_links import repository_resources


class InstallationStateError(Exception):
    """The requested installation state cannot be resolved."""


def resolve_absolute_path(raw: str, name: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise InstallationStateError(f"{name} must be an absolute path")
    return path.resolve(strict=False)


def build_report(
    root: Path,
    *,
    codex_home: str | None,
    skills_dir: str | None,
    agents_dir: str | None,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    home_path, home_source = _codex_home(codex_home, environment)
    expected_skills = home_path / "skills"
    expected_agents = home_path / "agents"
    skills_target, skills_source = _target(skills_dir, expected_skills, "--skills-dir")
    agents_target, agents_source = _target(agents_dir, expected_agents, "--agents-dir")
    findings: list[dict[str, str]] = []

    skills = _resource_report(
        root, "skills", skills_target, skills_source, expected_skills, findings
    )
    agents = _resource_report(
        root, "agents", agents_target, agents_source, expected_agents, findings
    )
    status = "mismatch" if findings else "ok"
    return {
        "status": status,
        "codex_home": {"path": str(home_path), "source": home_source},
        "skills": skills,
        "agents": agents,
        "rdl_command": None,
        "findings": findings,
    }


def render_text(report: Mapping[str, Any]) -> str:
    lines = [
        f"codex-installation status={report['status']}",
        f"codex_home={report['codex_home']['path']} source={report['codex_home']['source']}",
    ]
    for adapter in ("skills", "agents"):
        section = report[adapter]
        counts = section["counts"]
        lines.append(
            f"adapter={adapter} target={section['target']} "
            f"target_source={section['target_source']} "
            f"aligned={'yes' if section['aligned'] else 'no'} desired={counts['desired']} "
            f"expected={counts['expected']} missing={counts['missing']} "
            f"foreign={counts['foreign']} "
            f"managed={counts['managed']} stale={counts['stale']}"
        )
    command = report.get("rdl_command")
    if command is not None:
        lines.append(
            f"rdl_command target={command['target']} state={command['state']} "
            f"on_path={'yes' if command['on_path'] else 'no'} "
            f"shadowed_by={command['shadowed_by'] or 'none'}"
        )
    for finding in report["findings"]:
        lines.append(
            f"finding code={finding['code']} target={finding['target']} "
            f"remediation={finding['remediation']}"
        )
    return "\n".join(lines)


def _codex_home(raw: str | None, environment: Mapping[str, str]) -> tuple[Path, str]:
    if raw is not None:
        return resolve_absolute_path(raw, "--codex-home"), "argument"
    configured = environment.get("CODEX_HOME")
    if configured:
        return resolve_absolute_path(configured, "CODEX_HOME"), "environment"
    configured_home = environment.get("HOME")
    if configured_home:
        return resolve_absolute_path(configured_home, "HOME") / ".codex", "default"
    return Path.home().resolve(strict=False) / ".codex", "default"


def _target(raw: str | None, expected: Path, name: str) -> tuple[Path, str]:
    if raw is None:
        return expected, "codex-home"
    return resolve_absolute_path(raw, name), "argument"


def _resource_report(
    root: Path,
    adapter: str,
    target_dir: Path,
    target_source: str,
    expected_target: Path,
    findings: list[dict[str, str]],
) -> dict[str, Any]:
    desired, owned_roots = repository_resources(root, adapter)
    counts = {
        "desired": len(desired),
        "expected": 0,
        "missing": 0,
        "managed": 0,
        "foreign": 0,
        "non_link": 0,
        "broken": 0,
        "stale": 0,
    }
    entries: list[dict[str, Any]] = []
    aligned = target_dir == expected_target
    if not aligned:
        findings.append(
            _finding(
                f"{adapter}_target_mismatch",
                target_dir,
                f"use {expected_target} for this Codex launch home or launch Codex "
                "with the matching home",
            )
        )

    for name, source in sorted(desired.items()):
        target = target_dir / name
        state = inspect_link(target, source, owned_roots)
        entries.append(_entry(name, target, source, state, stale=False))
        if state.kind == "absent":
            counts["missing"] += 1
            findings.append(
                _finding(
                    f"{adapter}_link_missing",
                    target,
                    f"run the {adapter} installer for {target_dir}",
                )
            )
        elif state.kind != "symlink":
            counts["non_link"] += 1
            findings.append(
                _finding(
                    f"{adapter}_target_conflict",
                    target,
                    "move the user-owned target aside and reinstall",
                )
            )
        elif state.ownership == "expected" and state.health == "valid":
            counts["expected"] += 1
        elif state.ownership == "current-checkout":
            counts["managed"] += 1
            findings.append(
                _finding(
                    f"{adapter}_managed_link_stale",
                    target,
                    f"rerun the {adapter} installer",
                )
            )
        else:
            counts["foreign"] += 1
            findings.append(
                _finding(
                    f"{adapter}_foreign_link",
                    target,
                    "resolve the foreign link explicitly before reinstalling",
                )
            )
        if state.health == "broken":
            counts["broken"] += 1

    if target_dir.is_dir():
        desired_names = set(desired)
        for target in sorted(target_dir.iterdir(), key=lambda item: item.name):
            if target.name in desired_names or not target.is_symlink():
                continue
            state = inspect_link(target, None, owned_roots)
            if state.ownership != "current-checkout":
                continue
            counts["stale"] += 1
            entries.append(_entry(target.name, target, None, state, stale=True))
            findings.append(
                _finding(
                    f"{adapter}_retired_link",
                    target,
                    f"rerun the {adapter} installer",
                )
            )

    return {
        "target": str(target_dir),
        "target_source": target_source,
        "expected_target": str(expected_target),
        "aligned": aligned,
        "counts": counts,
        "entries": entries,
    }


def _entry(
    name: str,
    target: Path,
    source: Path | None,
    state: LinkState,
    *,
    stale: bool,
) -> dict[str, Any]:
    return {
        "name": name,
        "target": str(target),
        "source": str(source) if source is not None else None,
        "stale": stale,
        "kind": state.kind,
        "ownership": state.ownership,
        "health": state.health,
        "link_target": state.link_target,
    }


def _finding(code: str, target: Path, remediation: str) -> dict[str, str]:
    return {"code": code, "severity": "blocking", "target": str(target), "remediation": remediation}

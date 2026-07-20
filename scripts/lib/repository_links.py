"""Repository-specific desired link sets for installation adapters."""

from __future__ import annotations

import subprocess
from pathlib import Path


class RepositoryLinksError(Exception):
    """The repository does not expose a safe, complete desired link set."""


def repository_resources(root: Path, adapter: str) -> tuple[dict[str, Path], tuple[Path, ...]]:
    root = root.resolve(strict=True)
    if adapter == "skills":
        desired = _prepared_skills(root)
        return desired, (root / "local", root / "upstream")
    if adapter == "agents":
        source_dir = root / "codex" / "agents"
        desired = {
            path.name: path.resolve(strict=True)
            for path in sorted(source_dir.glob("*.toml"))
            if path.is_file()
        }
        if not desired:
            raise RepositoryLinksError(f"no recommended Codex agent configs found in {source_dir}")
        return desired, (source_dir,)
    raise ValueError(f"unknown adapter: {adapter}")


def _prepared_skills(root: Path) -> dict[str, Path]:
    expected = _manifest_skills(root)
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        raise RepositoryLinksError(
            f"generated skill directory is missing: {skills_dir}; "
            "run ./scripts/link_selected_skills.sh"
        )

    exposed = {path.name: path for path in skills_dir.iterdir() if path.is_symlink()}
    if set(exposed) != set(expected):
        missing = sorted(set(expected) - set(exposed))
        unexpected = sorted(set(exposed) - set(expected))
        raise RepositoryLinksError(
            f"generated skill links do not match selected-skills.conf: "
            f"missing={missing}; unexpected={unexpected}; "
            "run ./scripts/link_selected_skills.sh"
        )

    for name, source in expected.items():
        try:
            exposed_source = exposed[name].resolve(strict=True)
            expected_source = source.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RepositoryLinksError(
                f"generated skill link is unavailable: {exposed[name]}: {exc}; "
                "run ./scripts/link_selected_skills.sh"
            ) from exc
        if exposed_source != expected_source:
            raise RepositoryLinksError(
                f"generated skill link has the wrong source: {exposed[name]} -> "
                f"{exposed_source}; expected {expected_source}; "
                "run ./scripts/link_selected_skills.sh"
            )
    return {name: source.resolve(strict=True) for name, source in expected.items()}


def _manifest_skills(root: Path) -> dict[str, Path]:
    manifest = root / "selected-skills.conf"
    upstream_paths = _git_config_values(manifest, "upstream.mattpocock.path")
    if len(upstream_paths) != 1:
        raise RepositoryLinksError(f"missing upstream.mattpocock.path in {manifest}")
    upstream_path = _relative_repository_path(upstream_paths[0], manifest)
    records = [
        ("upstream", value)
        for value in _git_config_values(manifest, "upstream.mattpocock.skill")
    ]
    records.extend(
        ("local", value) for value in _git_config_values(manifest, "local.skill")
    )
    if not records:
        raise RepositoryLinksError(f"no selected skills are declared in {manifest}")

    desired: dict[str, Path] = {}
    for kind, raw_manifest_path in records:
        manifest_path = _relative_repository_path(raw_manifest_path, manifest)
        name = Path(manifest_path).name
        if name in desired:
            raise RepositoryLinksError(f"duplicate selected skill name: {name}")
        if kind == "upstream":
            source = root / upstream_path / manifest_path
        else:
            source = root / manifest_path
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            raise RepositoryLinksError(f"selected skill source is unavailable: {source}")
        desired[name] = source
    return desired


def _git_config_values(manifest: Path, key: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "config", "--file", str(manifest), "--get-all", key],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        raise RepositoryLinksError(f"cannot read selected skill manifest: {exc}") from exc
    if result.returncode == 1:
        return []
    if result.returncode != 0:
        detail = result.stderr.strip() or f"git config exited {result.returncode}"
        raise RepositoryLinksError(f"cannot read selected skill manifest: {detail}")
    return result.stdout.splitlines()


def _relative_repository_path(raw: str, manifest: Path) -> Path:
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts or not path.name:
        raise RepositoryLinksError(f"unsafe repository path in {manifest}: {raw}")
    return path

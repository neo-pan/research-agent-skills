#!/usr/bin/env python3
"""Compare or explicitly update a local folder from an Overleaf ZIP."""

from __future__ import annotations

import argparse
import filecmp
import fnmatch
import os
from pathlib import Path
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from urllib.parse import urlsplit


DEFAULT_IGNORE_PATTERNS = (
    ".git/**", ".codex/**", ".claude/**", "__pycache__/**", "node_modules/**",
    ".overleaf-sync/**", "overleaf_tmp/**", "__MACOSX/**", "*.pyc",
    "*.log", "*.aux", "*.out", "*.toc", "*.synctex.gz", ".gitignore",
    ".gitmodules", "AGENTS.md", "CLAUDE.md", "overleaf_tmp.zip",
)
ALLOWED_OVERLEAF_HOSTS = {"overleaf.com", "www.overleaf.com"}


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Allow redirects only when scheme, host, and port stay unchanged."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            old = urlsplit(req.full_url)
            new = urlsplit(newurl)
            old_port = old.port
            new_port = new.port
        except ValueError as exc:
            raise urllib.error.HTTPError(newurl, code, "invalid redirect URL", headers, fp) from exc
        old_origin = (
            old.scheme.lower(),
            (old.hostname or "").lower(),
            old_port if old_port is not None else _default_port(old.scheme),
        )
        new_origin = (
            new.scheme.lower(),
            (new.hostname or "").lower(),
            new_port if new_port is not None else _default_port(new.scheme),
        )
        if old_origin != new_origin:
            raise urllib.error.HTTPError(newurl, code, "cross-origin redirect refused", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_port(scheme: str) -> int | None:
    return {"http": 80, "https": 443}.get(scheme.lower())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", default="check", choices=("check", "update"))
    parser.add_argument("--url", default=os.environ.get("OVERLEAF_ZIP_URL"))
    parser.add_argument("--cookie", default=os.environ.get("OVERLEAF_COOKIE"))
    parser.add_argument("--cookie-file")
    parser.add_argument("--target", default=".")
    parser.add_argument("--ignore", action="append", default=[])
    parser.add_argument("--no-default-ignores", action="store_true")
    parser.add_argument(
        "--strip-single-root", action="store_true",
        help="Remove a known single wrapper directory from the ZIP; default: preserve paths.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args()


def read_cookie(args: argparse.Namespace) -> str:
    if args.cookie_file:
        cookie = Path(args.cookie_file).read_text(encoding="utf-8").strip()
    else:
        cookie = (args.cookie or "").strip()
    if not cookie:
        raise SystemExit("Missing Cookie. Pass --cookie-file or set OVERLEAF_COOKIE.")
    return cookie


def require_url(args: argparse.Namespace) -> str:
    url = (args.url or "").strip()
    if not url:
        raise SystemExit("Missing URL. Pass --url or set OVERLEAF_ZIP_URL.")
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise SystemExit("URL must use a valid port.") from exc
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() not in ALLOWED_OVERLEAF_HOSTS
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        raise SystemExit("URL must use HTTPS and an official Overleaf host.")
    if (parsed.hostname or "").lower() == "overleaf.com":
        parsed = parsed._replace(netloc="www.overleaf.com")
        return parsed.geturl()
    return url


def download_zip(url: str, cookie: str, output_path: Path, timeout: float) -> None:
    request = urllib.request.Request(url, headers={"Cookie": cookie, "User-Agent": "overleaf-project-sync/1.0"})
    try:
        opener = urllib.request.build_opener(SameOriginRedirectHandler())
        with opener.open(request, timeout=timeout) as response, output_path.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Download failed with HTTP {exc.code}. Check ZIP URL and Cookie.") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Download failed: {exc.reason}") from exc


def safe_extract(zip_path: Path, extract_dir: Path) -> None:
    root = extract_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            destination = (root / member.filename).resolve()
            if destination != root and root not in destination.parents:
                raise SystemExit(f"Unsafe ZIP member path: {member.filename}")
            mode = member.external_attr >> 16
            if mode and (mode & 0o170000) == 0o120000:
                raise SystemExit(f"Unsafe ZIP symlink member: {member.filename}")
        archive.extractall(root)


def choose_remote_root(extract_dir: Path, strip_single_root: bool) -> Path:
    if not strip_single_root:
        return extract_dir
    entries = [p for p in extract_dir.iterdir() if p.name != "__MACOSX"]
    dirs = [p for p in entries if p.is_dir()]
    if len(dirs) == 1 and not any(p.is_file() for p in entries):
        return dirs[0]
    raise SystemExit("Expected a single ZIP wrapper directory for --strip-single-root.")


def is_ignored(rel_path: str, patterns: tuple[str, ...], is_dir: bool = False) -> bool:
    rel_path = rel_path.replace(os.sep, "/").strip("/")
    candidates = {rel_path, Path(rel_path).name}
    if is_dir:
        candidates.update({f"{rel_path}/", f"{rel_path}/**"})
    return any(
        fnmatch.fnmatch(candidate, pattern.replace("\\", "/").strip("/"))
        for pattern in patterns for candidate in candidates
    )


def collect_files(root: Path, patterns: tuple[str, ...]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for current_root, dirnames, filenames in os.walk(root):
        current = Path(current_root)
        rel_dir = current.relative_to(root).as_posix()
        if rel_dir == ".":
            rel_dir = ""
        dirnames[:] = [d for d in dirnames if not is_ignored(f"{rel_dir}/{d}" if rel_dir else d, patterns, True)]
        for filename in filenames:
            rel = f"{rel_dir}/{filename}" if rel_dir else filename
            if not is_ignored(rel, patterns):
                result[rel] = current / filename
    return result


def compare_files(remote_root: Path, target_root: Path, patterns: tuple[str, ...]):
    remote = collect_files(remote_root, patterns)
    local = collect_files(target_root, patterns)
    changed = [rel for rel in sorted(remote) if rel in local and not filecmp.cmp(remote[rel], local[rel], shallow=False)]
    missing = [rel for rel in sorted(remote) if rel not in local]
    extra = [rel for rel in sorted(local) if rel not in remote]
    return changed, missing, extra, remote


def print_group(title: str, paths: list[str]) -> None:
    if paths:
        print(title)
        for path in paths:
            print(f"  - {path}")
        print()


def safe_destination(target_root: Path, relative: str) -> Path:
    """Return a regular-file destination that cannot escape target_root."""
    destination = target_root / relative
    root = target_root.resolve()
    try:
        destination.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"Unsafe target path: {relative}") from exc

    current = target_root
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            raise SystemExit(f"Refusing symlink target: {relative}")
        if current != destination and current.exists() and not current.is_dir():
            raise SystemExit(f"Refusing non-directory parent: {current}")
    if destination.exists() and not destination.is_file():
        raise SystemExit(f"Refusing non-file target: {relative}")
    return destination


def main() -> int:
    args = parse_args()
    url = require_url(args)
    cookie = read_cookie(args)
    target_root = Path(args.target).resolve()
    if not target_root.is_dir():
        raise SystemExit(f"Target directory does not exist: {target_root}")
    patterns = tuple(() if args.no_default_ignores else DEFAULT_IGNORE_PATTERNS) + tuple(args.ignore)
    with tempfile.TemporaryDirectory(prefix="overleaf-sync-") as temp_name:
        temp_dir = Path(temp_name)
        zip_path = temp_dir / "project.zip"
        extract_dir = temp_dir / "extract"
        extract_dir.mkdir()
        download_zip(url, cookie, zip_path, args.timeout)
        safe_extract(zip_path, extract_dir)
        remote_root = choose_remote_root(extract_dir, args.strip_single_root)
        changed, missing, extra, remote_files = compare_files(remote_root, target_root, patterns)
        print_group("Changed files:", changed)
        print_group("Missing locally, present in Overleaf:", missing)
        print_group("Extra locally, absent from Overleaf:", extra)
        if not changed and not missing and not extra:
            print("OK: local target matches the Overleaf ZIP under current ignore rules.")
        if args.mode == "check":
            return 0 if not changed and not missing and not extra else 2
        dry_run = args.dry_run or not args.overwrite
        destinations = [(rel, safe_destination(target_root, rel)) for rel in sorted(remote_files)]
        for rel, destination in destinations:
            remote_path = remote_files[rel]
            if dry_run:
                print(f"DRY-RUN copy: {rel}")
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(remote_path, destination)
            print(f"copied: {rel}")
        print("Dry run complete. No files were written." if dry_run else "Update complete. Local-only files were not deleted.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

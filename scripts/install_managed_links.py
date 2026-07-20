#!/usr/bin/env python3
"""Repository adapters for the shared managed-link module."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.managed_links import ManagedLinkError, install_batch
from lib.repository_links import RepositoryLinksError, repository_resources


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install repository-managed links.")
    parser.add_argument("adapter", choices=("skills", "agents"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--target-dir", required=True)
    return parser


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve(strict=True)
    target_dir = Path(args.target_dir).expanduser().resolve(strict=False)
    desired, owned_roots = repository_resources(root, args.adapter)
    result = install_batch(target_dir, desired, owned_roots)
    print(
        f"adapter={args.adapter} status=ok target={target_dir} desired={result.desired} "
        f"created={result.created} replaced={result.replaced} "
        f"unchanged={result.unchanged} pruned={result.pruned}"
    )
    return 0


def main() -> int:
    try:
        return run()
    except (ManagedLinkError, RepositoryLinksError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

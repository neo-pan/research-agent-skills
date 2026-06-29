#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "${1:-}" in
  "")
    "${ROOT_DIR}/scripts/check.sh" --fast
    ;;
  -h|--help)
    "${ROOT_DIR}/scripts/check.sh" --help
    ;;
  *)
    "${ROOT_DIR}/scripts/check.sh" "$@"
    ;;
esac

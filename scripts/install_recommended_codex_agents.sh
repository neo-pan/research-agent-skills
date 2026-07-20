#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-${CODEX_HOME:-${HOME}/.codex}/agents}"

exec python3 "${ROOT_DIR}/scripts/install_managed_links.py" \
  agents \
  --root "${ROOT_DIR}" \
  --target-dir "${TARGET_DIR}"

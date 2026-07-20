#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-${CODEX_HOME:-${HOME}/.codex}/skills}"

"${ROOT_DIR}/scripts/check.sh" >/dev/null
exec python3 "${ROOT_DIR}/scripts/install_managed_links.py" \
  skills \
  --root "${ROOT_DIR}" \
  --target-dir "${TARGET_DIR}"

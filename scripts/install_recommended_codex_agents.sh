#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/install_recommended_codex_agents.sh [target-agents-dir]

Install the recommended Codex agent links into the default or explicit target directory.
EOF
}

if [[ "$#" -gt 1 ]]; then
  usage >&2
  exit 2
fi

case "${1:-}" in
  "")
    TARGET_DIR="${CODEX_HOME:-${HOME}/.codex}/agents"
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  -*)
    usage >&2
    exit 2
    ;;
  *)
    TARGET_DIR="$1"
    ;;
esac

exec python3 "${ROOT_DIR}/scripts/install_managed_links.py" \
  agents \
  --root "${ROOT_DIR}" \
  --target-dir "${TARGET_DIR}"

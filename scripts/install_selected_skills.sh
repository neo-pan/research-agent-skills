#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage: scripts/install_selected_skills.sh [target-skills-dir]

Install the selected skill links into the default or explicit target directory.
EOF
}

if [[ "$#" -gt 1 ]]; then
  usage >&2
  exit 2
fi

case "${1:-}" in
  "")
    TARGET_DIR="${CODEX_HOME:-${HOME}/.codex}/skills"
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

"${ROOT_DIR}/scripts/check.sh" >/dev/null
exec python3 "${ROOT_DIR}/scripts/install_managed_links.py" \
  skills \
  --root "${ROOT_DIR}" \
  --target-dir "${TARGET_DIR}"

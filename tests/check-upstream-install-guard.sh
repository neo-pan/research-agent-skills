#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GUARD_FILE="${ROOT_DIR}/upstream/AGENTS.md"

if [[ ! -f "${GUARD_FILE}" ]]; then
  echo "Missing upstream install guard: ${GUARD_FILE}" >&2
  exit 1
fi

if ! grep -q "not an installation entry point" "${GUARD_FILE}"; then
  echo "Upstream install guard must state that upstream is not an installation entry point." >&2
  exit 1
fi

if ! grep -q "selected-skills.conf" "${GUARD_FILE}"; then
  echo "Upstream install guard must point installers to selected-skills.conf." >&2
  exit 1
fi


#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-${CODEX_HOME:-${HOME}/.codex}/skills}"

"${ROOT_DIR}/scripts/check.sh" >/dev/null

mkdir -p "${TARGET_DIR}"

installed=0
for skill_path in "${ROOT_DIR}"/skills/*; do
  if [[ ! -L "${skill_path}" ]]; then
    continue
  fi

  skill_name="$(basename "${skill_path}")"
  ln -sfn "$(realpath "${skill_path}")" "${TARGET_DIR}/${skill_name}"
  installed=$((installed + 1))
done

echo "Installed ${installed} selected skills into ${TARGET_DIR}"


#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-${CODEX_HOME:-${HOME}/.codex}/skills}"

source "${ROOT_DIR}/scripts/lib/installed_skills.sh"

"${ROOT_DIR}/scripts/check.sh" >/dev/null

mkdir -p "${TARGET_DIR}"

for skill_path in "${ROOT_DIR}"/skills/*; do
  [[ -L "${skill_path}" ]] || continue

  target_path="${TARGET_DIR}/$(basename "${skill_path}")"
  if [[ -e "${target_path}" && ! -L "${target_path}" ]]; then
    echo "Refusing to replace non-symlink skill install: ${target_path}" >&2
    exit 1
  fi
done

selected_skills_remove_stale_managed_links "${ROOT_DIR}" "${TARGET_DIR}"

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
if [[ "${SELECTED_SKILLS_REMOVED_STALE}" -gt 0 ]]; then
  echo "Removed ${SELECTED_SKILLS_REMOVED_STALE} stale skill links previously managed by this repository"
fi

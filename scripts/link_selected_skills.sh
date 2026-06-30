#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="${ROOT_DIR}/skills"

source "${ROOT_DIR}/scripts/lib/selected_skills.sh"

selected_skills_load "${ROOT_DIR}"
selected_skills_validate_manifest

mkdir -p "${SKILLS_DIR}"
touch "${SKILLS_DIR}/.gitkeep"
find "${SKILLS_DIR}" -maxdepth 1 -type l -delete

link_selected_skill() {
  local _kind="$1"
  local skill_name="$2"
  local source_path="$3"
  local _manifest_path="$4"
  local target_path="${SKILLS_DIR}/${skill_name}"

  ln -sfn "${source_path}" "${target_path}"
}

selected_skills_each link_selected_skill

total_count="$(selected_skills_count)"
echo "Linked ${total_count} skills under ${SKILLS_DIR}"

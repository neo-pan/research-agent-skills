#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="${ROOT_DIR}/skills"
MANIFEST="${ROOT_DIR}/selected-skills.conf"

UPSTREAM_PATH="$(git config --file "${MANIFEST}" --get upstream.mattpocock.path)"
UPSTREAM_DIR="${ROOT_DIR}/${UPSTREAM_PATH}"

if [[ ! -d "${UPSTREAM_DIR}/.git" && ! -f "${UPSTREAM_DIR}/.git" ]]; then
  cat >&2 <<EOF
Missing upstream submodule:
  ${UPSTREAM_DIR}

Run:
  git -C "${ROOT_DIR}" submodule update --init --recursive
EOF
  exit 1
fi

mapfile -t selected_skills < <(git config --file "${MANIFEST}" --get-all upstream.mattpocock.skill || true)
mapfile -t local_skills < <(git config --file "${MANIFEST}" --get-all local.skill || true)

mkdir -p "${SKILLS_DIR}"
touch "${SKILLS_DIR}/.gitkeep"
find "${SKILLS_DIR}" -maxdepth 1 -type l -delete

for skill_path in "${selected_skills[@]}"; do
  source_path="${UPSTREAM_DIR}/${skill_path}"
  skill_name="$(basename "${skill_path}")"
  target_path="${SKILLS_DIR}/${skill_name}"

  if [[ ! -d "${source_path}" ]]; then
    echo "Missing selected skill in upstream: ${skill_path}" >&2
    exit 1
  fi

  ln -sfn "${source_path}" "${target_path}"
done

for skill_path in "${local_skills[@]}"; do
  source_path="${ROOT_DIR}/${skill_path}"
  skill_name="$(basename "${skill_path}")"
  target_path="${SKILLS_DIR}/${skill_name}"

  if [[ ! -d "${source_path}" ]]; then
    echo "Missing local skill: ${skill_path}" >&2
    exit 1
  fi

  ln -sfn "${source_path}" "${target_path}"
done

total_count=$((${#selected_skills[@]} + ${#local_skills[@]}))
echo "Linked ${total_count} skills under ${SKILLS_DIR}"

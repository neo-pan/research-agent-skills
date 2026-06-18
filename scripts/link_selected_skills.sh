#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_DIR="${ROOT_DIR}/upstream/mattpocock-skills"
SKILLS_DIR="${ROOT_DIR}/skills"

if [[ ! -d "${UPSTREAM_DIR}/.git" && ! -f "${UPSTREAM_DIR}/.git" ]]; then
  cat >&2 <<EOF
Missing upstream submodule:
  ${UPSTREAM_DIR}

Run:
  git -C "${ROOT_DIR}" submodule update --init --recursive
EOF
  exit 1
fi

selected_skills=(
  "skills/engineering/grill-with-docs"
  "skills/engineering/domain-modeling"
  "skills/engineering/codebase-design"
  "skills/engineering/improve-codebase-architecture"
  "skills/engineering/diagnosing-bugs"
  "skills/engineering/tdd"
  "skills/engineering/to-prd"
  "skills/engineering/to-issues"
  "skills/engineering/prototype"
  "skills/productivity/grill-me"
  "skills/productivity/handoff"
  "skills/productivity/writing-great-skills"
)

mkdir -p "${SKILLS_DIR}"
touch "${SKILLS_DIR}/.gitkeep"

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

echo "Linked ${#selected_skills[@]} selected skills under ${SKILLS_DIR}"


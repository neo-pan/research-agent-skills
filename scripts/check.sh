#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="${ROOT_DIR}/selected-skills.conf"

UPSTREAM_PATH="$(git config --file "${MANIFEST}" --get upstream.mattpocock.path)"
UPSTREAM_DIR="${ROOT_DIR}/${UPSTREAM_PATH}"

if [[ ! -d "${UPSTREAM_DIR}/.git" && ! -f "${UPSTREAM_DIR}/.git" ]]; then
  echo "Missing upstream submodule: ${UPSTREAM_DIR}" >&2
  exit 1
fi

mapfile -t selected_skills < <(git config --file "${MANIFEST}" --get-all upstream.mattpocock.skill || true)
mapfile -t local_skills < <(git config --file "${MANIFEST}" --get-all local.skill || true)

missing=0
for skill_path in "${selected_skills[@]}"; do
  skill_dir="${UPSTREAM_DIR}/${skill_path}"
  if [[ ! -d "${skill_dir}" ]]; then
    echo "upstream: missing directory ${skill_dir}" >&2
    missing=1
  elif [[ ! -f "${skill_dir}/SKILL.md" ]]; then
    echo "upstream: missing SKILL.md ${skill_dir}/SKILL.md" >&2
    missing=1
  fi
done

for skill_path in "${local_skills[@]}"; do
  skill_dir="${ROOT_DIR}/${skill_path}"
  if [[ ! -d "${skill_dir}" ]]; then
    echo "local: missing directory ${skill_dir}" >&2
    missing=1
  elif [[ ! -f "${skill_dir}/SKILL.md" ]]; then
    echo "local: missing SKILL.md ${skill_dir}/SKILL.md" >&2
    missing=1
  fi
done

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

total_count=$((${#selected_skills[@]} + ${#local_skills[@]}))
echo "Manifest ok: ${total_count} skills"

"${ROOT_DIR}/scripts/link_selected_skills.sh" >/dev/null

broken_links=0
while IFS= read -r -d '' link_path; do
  if [[ ! -e "${link_path}" ]]; then
    echo "Broken skill link: ${link_path}" >&2
    broken_links=1
  fi
done < <(find "${ROOT_DIR}/skills" -maxdepth 1 -type l -print0)

if [[ "${broken_links}" -ne 0 ]]; then
  exit 1
fi

echo "Skill links ok"

for test_script in "${ROOT_DIR}"/local/research-dev-loop/tests/*.sh; do
  test_name="$(basename "${test_script}")"
  start_seconds="${SECONDS}"
  echo "RDL shell test start: ${test_name}"
  bash "${test_script}" >/dev/null
  echo "RDL shell test ok: ${test_name} ($((SECONDS - start_seconds))s)"
done

echo "RDL tests ok"

RDL_PYTHON_BIN="${RDL_PYTHON_BIN:-python3}"
if ! command -v "${RDL_PYTHON_BIN}" >/dev/null 2>&1; then
  echo "Missing python3: RDL Python tests require python3 for repository checks." >&2
  exit 1
fi

PYTHONPATH="${ROOT_DIR}/local/research-dev-loop" \
  "${RDL_PYTHON_BIN}" -m unittest discover -s "${ROOT_DIR}/local/research-dev-loop/tests_py" >/dev/null

echo "RDL Python tests ok"

bash "${ROOT_DIR}/tests/check-python-prereq.sh" >/dev/null

echo "Check prerequisites ok"

#!/usr/bin/env bash

# Shared selected-skill manifest helpers. Source this file from repository
# scripts; do not execute it directly.

selected_skills_load() {
  if [[ "$#" -ne 1 ]]; then
    echo "selected_skills_load requires ROOT_DIR" >&2
    return 2
  fi

  SELECTED_SKILLS_ROOT_DIR="$1"
  SELECTED_SKILLS_MANIFEST="${SELECTED_SKILLS_ROOT_DIR}/selected-skills.conf"
  SELECTED_SKILLS_UPSTREAM_PATH="$(git config --file "${SELECTED_SKILLS_MANIFEST}" --get upstream.mattpocock.path || true)"
  SELECTED_SKILLS_UPSTREAM_DIR="${SELECTED_SKILLS_ROOT_DIR}/${SELECTED_SKILLS_UPSTREAM_PATH}"

  mapfile -t SELECTED_SKILLS_UPSTREAM_MANIFEST_PATHS < <(
    git config --file "${SELECTED_SKILLS_MANIFEST}" --get-all upstream.mattpocock.skill || true
  )
  mapfile -t SELECTED_SKILLS_LOCAL_MANIFEST_PATHS < <(
    git config --file "${SELECTED_SKILLS_MANIFEST}" --get-all local.skill || true
  )

  SELECTED_SKILLS_RECORD_KINDS=()
  SELECTED_SKILLS_RECORD_NAMES=()
  SELECTED_SKILLS_RECORD_SOURCES=()
  SELECTED_SKILLS_RECORD_MANIFEST_PATHS=()

  local skill_path
  for skill_path in "${SELECTED_SKILLS_UPSTREAM_MANIFEST_PATHS[@]}"; do
    _selected_skills_add_record \
      "upstream" \
      "$(basename "${skill_path}")" \
      "${SELECTED_SKILLS_UPSTREAM_DIR}/${skill_path}" \
      "${skill_path}"
  done

  for skill_path in "${SELECTED_SKILLS_LOCAL_MANIFEST_PATHS[@]}"; do
    _selected_skills_add_record \
      "local" \
      "$(basename "${skill_path}")" \
      "${SELECTED_SKILLS_ROOT_DIR}/${skill_path}" \
      "${skill_path}"
  done
}

selected_skills_count() {
  echo "${#SELECTED_SKILLS_RECORD_NAMES[@]}"
}

selected_skills_upstream_dir() {
  echo "${SELECTED_SKILLS_UPSTREAM_DIR}"
}

selected_skills_validate_upstream_path() {
  if [[ ! -f "${SELECTED_SKILLS_MANIFEST}" ]]; then
    echo "Missing selected skill manifest: ${SELECTED_SKILLS_MANIFEST}" >&2
    return 1
  fi

  if [[ -z "${SELECTED_SKILLS_UPSTREAM_PATH}" ]]; then
    echo "Missing upstream.mattpocock.path in ${SELECTED_SKILLS_MANIFEST}" >&2
    return 1
  fi

  return 0
}

selected_skills_each() {
  if [[ "$#" -ne 1 ]]; then
    echo "selected_skills_each requires callback function name" >&2
    return 2
  fi

  local callback="$1"
  local index
  for index in "${!SELECTED_SKILLS_RECORD_NAMES[@]}"; do
    "${callback}" \
      "${SELECTED_SKILLS_RECORD_KINDS[$index]}" \
      "${SELECTED_SKILLS_RECORD_NAMES[$index]}" \
      "${SELECTED_SKILLS_RECORD_SOURCES[$index]}" \
      "${SELECTED_SKILLS_RECORD_MANIFEST_PATHS[$index]}"
  done
}

selected_skills_validate_manifest() {
  local errors=0

  if ! selected_skills_validate_upstream_path; then
    errors=1
  elif [[ ! -d "${SELECTED_SKILLS_UPSTREAM_DIR}/.git" && ! -f "${SELECTED_SKILLS_UPSTREAM_DIR}/.git" ]]; then
    cat >&2 <<EOF
Missing upstream submodule:
  ${SELECTED_SKILLS_UPSTREAM_DIR}

Run:
  git -C "${SELECTED_SKILLS_ROOT_DIR}" submodule update --init --recursive
EOF
    errors=1
  fi

  local index
  local skill_name
  local source_path
  local seen_names=()
  for index in "${!SELECTED_SKILLS_RECORD_NAMES[@]}"; do
    skill_name="${SELECTED_SKILLS_RECORD_NAMES[$index]}"
    source_path="${SELECTED_SKILLS_RECORD_SOURCES[$index]}"

    if _selected_skills_name_seen "${skill_name}" "${seen_names[@]}"; then
      echo "Duplicate selected skill name: ${skill_name}" >&2
      errors=1
    fi
    seen_names+=("${skill_name}")

    if [[ ! -d "${source_path}" ]]; then
      echo "${SELECTED_SKILLS_RECORD_KINDS[$index]}: missing directory ${source_path}" >&2
      errors=1
    elif [[ ! -f "${source_path}/SKILL.md" ]]; then
      echo "${SELECTED_SKILLS_RECORD_KINDS[$index]}: missing SKILL.md ${source_path}/SKILL.md" >&2
      errors=1
    fi
  done

  return "${errors}"
}

_selected_skills_add_record() {
  SELECTED_SKILLS_RECORD_KINDS+=("$1")
  SELECTED_SKILLS_RECORD_NAMES+=("$2")
  SELECTED_SKILLS_RECORD_SOURCES+=("$3")
  SELECTED_SKILLS_RECORD_MANIFEST_PATHS+=("$4")
}

_selected_skills_name_seen() {
  local candidate="$1"
  shift

  local existing
  for existing in "$@"; do
    if [[ "${existing}" == "${candidate}" ]]; then
      return 0
    fi
  done
  return 1
}

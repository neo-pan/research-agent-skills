#!/usr/bin/env bash

# Helpers for maintaining skill links previously installed from this repository.
# Source this file from installer scripts; do not execute it directly.

selected_skills_remove_stale_managed_links() {
  if [[ "$#" -ne 2 ]]; then
    echo "selected_skills_remove_stale_managed_links requires ROOT_DIR and TARGET_DIR" >&2
    return 2
  fi

  local root_dir="$1"
  local target_dir="$2"
  local target_path
  local target_source
  local skill_name

  SELECTED_SKILLS_REMOVED_STALE=0

  for target_path in "${target_dir}"/*; do
    [[ -L "${target_path}" ]] || continue

    target_source="$(readlink "${target_path}")"
    case "${target_source}" in
      "${root_dir}/local/"*|"${root_dir}/upstream/"*)
        skill_name="$(basename "${target_path}")"
        if [[ ! -L "${root_dir}/skills/${skill_name}" ]]; then
          rm "${target_path}"
          SELECTED_SKILLS_REMOVED_STALE=$((SELECTED_SKILLS_REMOVED_STALE + 1))
        fi
        ;;
    esac
  done
}

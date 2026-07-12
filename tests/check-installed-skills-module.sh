#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

source "${ROOT_DIR}/scripts/lib/installed_skills.sh"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

fixture_root="${tmp_dir}/repo"
target_dir="${tmp_dir}/installed"
external_dir="${tmp_dir}/external"

mkdir -p \
  "${fixture_root}/local/current" \
  "${fixture_root}/skills" \
  "${target_dir}" \
  "${external_dir}/external-skill"

ln -s "${fixture_root}/local/current" "${fixture_root}/skills/current"
ln -s "${fixture_root}/local/current" "${target_dir}/current"
ln -s "${fixture_root}/upstream/source/retired" "${target_dir}/retired"
ln -s "${external_dir}/external-skill" "${target_dir}/external"
printf 'user-owned\n' >"${target_dir}/regular-file"

selected_skills_remove_stale_managed_links "${fixture_root}" "${target_dir}"

[[ "${SELECTED_SKILLS_REMOVED_STALE}" == "1" ]] \
  || fail "expected one stale managed link to be removed"
[[ ! -e "${target_dir}/retired" && ! -L "${target_dir}/retired" ]] \
  || fail "stale managed link was not removed"
[[ -L "${target_dir}/current" ]] \
  || fail "currently selected managed link was removed"
[[ -L "${target_dir}/external" ]] \
  || fail "external skill link was removed"
[[ -f "${target_dir}/regular-file" ]] \
  || fail "regular user-owned file was removed"

echo "Installed skills module ok"

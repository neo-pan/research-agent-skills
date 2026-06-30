#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

source "${ROOT_DIR}/scripts/lib/selected_skills.sh"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

write_manifest() {
  local fixture_root="$1"
  local upstream_path="${2:-upstream/mattpocock-skills}"
  cat >"${fixture_root}/selected-skills.conf" <<EOF
[upstream "mattpocock"]
    repo = https://example.invalid/skills
    path = ${upstream_path}
    commitPolicy = pinned-submodule
    skill = skills/engineering/upstream-alpha

[local]
    skill = local/local-beta
EOF
}

create_skill() {
  local skill_dir="$1"
  mkdir -p "${skill_dir}"
  printf '# Skill\n' >"${skill_dir}/SKILL.md"
}

create_valid_fixture() {
  local fixture_root="$1"
  write_manifest "${fixture_root}"
  mkdir -p "${fixture_root}/upstream/mattpocock-skills/.git"
  create_skill "${fixture_root}/upstream/mattpocock-skills/skills/engineering/upstream-alpha"
  create_skill "${fixture_root}/local/local-beta"
}

collect_record() {
  records+=("$1|$2|$3|$4")
}

assert_valid_fixture() {
  local fixture_root="${tmp_dir}/valid-fixture"
  mkdir -p "${fixture_root}"
  create_valid_fixture "${fixture_root}"

  selected_skills_load "${fixture_root}"
  selected_skills_validate_manifest

  [[ "$(selected_skills_count)" == "2" ]] \
    || fail "valid fixture should expose 2 selected skills"

  records=()
  selected_skills_each collect_record

  [[ "${#records[@]}" == "2" ]] \
    || fail "valid fixture iteration should return 2 records"
  [[ "${records[*]}" == *"upstream|upstream-alpha|"* ]] \
    || fail "valid fixture missing upstream-alpha record"
  [[ "${records[*]}" == *"local|local-beta|"* ]] \
    || fail "valid fixture missing local-beta record"
}

assert_current_repository_manifest() {
  selected_skills_load "${ROOT_DIR}"
  selected_skills_validate_manifest

  local expected_count
  expected_count=$(
    (
      git config --file "${ROOT_DIR}/selected-skills.conf" --get-all upstream.mattpocock.skill || true
      git config --file "${ROOT_DIR}/selected-skills.conf" --get-all local.skill || true
    ) | wc -l
  )
  local actual_count
  actual_count="$(selected_skills_count)"

  [[ "${actual_count}" == "${expected_count}" ]] \
    || fail "expected ${expected_count} selected skill records, got ${actual_count}"
}

assert_invalid_fixture() {
  local name="$1"
  local expected_message="$2"
  local fixture_root="${tmp_dir}/${name}"
  shift 2

  mkdir -p "${fixture_root}"
  "$@" "${fixture_root}"

  selected_skills_load "${fixture_root}"
  if selected_skills_validate_manifest >"${tmp_dir}/${name}.stdout" 2>"${tmp_dir}/${name}.stderr"; then
    fail "${name}: validation unexpectedly passed"
  fi

  grep -q "${expected_message}" "${tmp_dir}/${name}.stderr" \
    || fail "${name}: expected error containing '${expected_message}'"
}

fixture_missing_upstream_path() {
  cat >"$1/selected-skills.conf" <<'EOF'
[upstream "mattpocock"]
    repo = https://example.invalid/skills
    commitPolicy = pinned-submodule

[local]
    skill = local/local-beta
EOF
  create_skill "$1/local/local-beta"
}

fixture_missing_submodule() {
  create_valid_fixture "$1"
  rm -rf "$1/upstream/mattpocock-skills/.git"
}

fixture_missing_upstream_skill_dir() {
  create_valid_fixture "$1"
  rm -rf "$1/upstream/mattpocock-skills/skills/engineering/upstream-alpha"
}

fixture_missing_local_skill_dir() {
  create_valid_fixture "$1"
  rm -rf "$1/local/local-beta"
}

fixture_missing_skill_md() {
  create_valid_fixture "$1"
  rm -f "$1/local/local-beta/SKILL.md"
}

fixture_duplicate_skill_name() {
  write_manifest "$1"
  cat >>"$1/selected-skills.conf" <<'EOF'
    skill = local/upstream-alpha
EOF
  mkdir -p "$1/upstream/mattpocock-skills/.git"
  create_skill "$1/upstream/mattpocock-skills/skills/engineering/upstream-alpha"
  create_skill "$1/local/local-beta"
  create_skill "$1/local/upstream-alpha"
}

assert_valid_fixture
assert_current_repository_manifest
assert_invalid_fixture "missing-upstream-path" "Missing upstream.mattpocock.path" fixture_missing_upstream_path
assert_invalid_fixture "missing-submodule" "Missing upstream submodule" fixture_missing_submodule
assert_invalid_fixture "missing-upstream-skill-dir" "upstream: missing directory" fixture_missing_upstream_skill_dir
assert_invalid_fixture "missing-local-skill-dir" "local: missing directory" fixture_missing_local_skill_dir
assert_invalid_fixture "missing-skill-md" "local: missing SKILL.md" fixture_missing_skill_md
assert_invalid_fixture "duplicate-skill-name" "Duplicate selected skill name: upstream-alpha" fixture_duplicate_skill_name

if grep -q 'upstream/mattpocock-skills' "${ROOT_DIR}/scripts/update_upstream.sh"; then
  fail "update_upstream.sh still hardcodes upstream/mattpocock-skills"
fi

echo "Selected skills module ok"

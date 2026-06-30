#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

source "${ROOT_DIR}/scripts/lib/selected_skills.sh"

selected_skills_load "${ROOT_DIR}"
selected_skills_validate_manifest

expected_count=$(
  (
    git config --file "${ROOT_DIR}/selected-skills.conf" --get-all upstream.mattpocock.skill || true
    git config --file "${ROOT_DIR}/selected-skills.conf" --get-all local.skill || true
  ) | wc -l
)
actual_count="$(selected_skills_count)"

[[ "${actual_count}" == "${expected_count}" ]] \
  || fail "expected ${expected_count} selected skill records, got ${actual_count}"

records=()
collect_record() {
  records+=("$1|$2|$3|$4")
}

selected_skills_each collect_record

[[ "${#records[@]}" == "${expected_count}" ]] \
  || fail "iteration returned ${#records[@]} records, expected ${expected_count}"

has_codebase_design=0
has_phase_review=0
for record in "${records[@]}"; do
  case "${record}" in
    upstream\|codebase-design\|*/upstream/mattpocock-skills/skills/engineering/codebase-design\|skills/engineering/codebase-design)
      has_codebase_design=1
      ;;
    local\|phase-review\|*/local/phase-review\|local/phase-review)
      has_phase_review=1
      ;;
  esac
done

[[ "${has_codebase_design}" -eq 1 ]] \
  || fail "missing resolved upstream codebase-design record"
[[ "${has_phase_review}" -eq 1 ]] \
  || fail "missing resolved local phase-review record"

echo "Selected skills module ok: ${actual_count} records"

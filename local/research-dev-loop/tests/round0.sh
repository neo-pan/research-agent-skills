#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RDL="${ROOT_DIR}/local/research-dev-loop/scripts/rdl.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_file() {
  [[ -f "$1" ]] || fail "missing file: $1"
}

assert_contains() {
  local file="$1"
  local pattern="$2"
  grep -q "${pattern}" "${file}" || fail "missing pattern ${pattern} in ${file}"
}

for template in \
  artifact-manifest.json \
  decision-ledger.md \
  decision.md \
  evidence.md \
  factors.md \
  final-report.md \
  intent.md \
  interpretation.md \
  mission.md \
  progress.md \
  prompt.md \
  review.md \
  work.md; do
  assert_file "${ROOT_DIR}/local/research-dev-loop/templates/${template}"
done

tmp_root="$(mktemp -d)"
trap 'rm -rf "${tmp_root}"' EXIT

repo="${tmp_root}/repo"
mkdir -p "${repo}"
cat > "${repo}/mission.md" <<'MISSION'
# Mission

Round 0 fixture mission.
MISSION

cd "${repo}"

"${RDL}" start research mission.md --session-id r1 > start-research.json
assert_contains start-research.json '"status": "ok"'
assert_contains start-research.json '"action": "start"'
assert_file ".rdl/sessions/r1/state.json"
assert_file ".rdl/sessions/r1/integrity.json"
assert_file ".rdl/sessions/r1/mission.md"
assert_file ".rdl/sessions/r1/factors.md"
assert_file ".rdl/sessions/r1/artifact-manifest.json"
assert_file ".rdl/sessions/r1/decision-ledger.md"
assert_file ".rdl/sessions/r1/progress.md"
assert_file ".rdl/sessions/r1/rounds/001/prompt.md"
assert_contains ".rdl/sessions/r1/state.json" '"mode": "research"'
assert_contains ".rdl/sessions/r1/state.json" '"guard_session_id": null'
assert_contains ".rdl/sessions/r1/state.json" '"last_guard_command_id": null'
assert_contains ".rdl/sessions/r1/integrity.json" '"entries": \['
assert_contains ".rdl/sessions/r1/integrity.json" '"path":"state.json"'
assert_contains ".rdl/sessions/r1/integrity.json" '"policy":"cli_owned"'
assert_contains ".rdl/sessions/r1/integrity.json" '"sha256":"[0-9a-f]\{64\}"'

if "${RDL}" start research mission.md --session-id r2 > second-start.json; then
  fail "second active session unexpectedly succeeded"
fi
assert_contains second-start.json '"status": "blocked"'

"${RDL}" status > status.json
assert_contains status.json '"status": "ok"'
assert_contains status.json '"action": "status"'
assert_contains status.json '"session_id": "r1"'
assert_contains status.json '"mode": "research"'

repo2="${tmp_root}/repo2"
mkdir -p "${repo2}"
cat > "${repo2}/plan.md" <<'PLAN'
# Build Plan

Fixture build mission.
PLAN

cd "${repo2}"
"${RDL}" start build plan.md --session-id b1 > start-build.json
assert_contains start-build.json '"status": "ok"'
assert_contains ".rdl/sessions/b1/state.json" '"mode": "build"'

echo "round0 tests ok"

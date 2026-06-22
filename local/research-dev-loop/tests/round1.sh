#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
RDL="${ROOT_DIR}/local/research-dev-loop/scripts/rdl.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_file_contains() {
  local file="$1"
  local pattern="$2"
  grep -q "${pattern}" "${file}" || fail "missing pattern ${pattern} in ${file}"
}

assert_fails() {
  local output="$1"
  shift
  if "$@" > "${output}"; then
    fail "command unexpectedly succeeded: $*"
  fi
}

tmp_root="$(mktemp -d)"
trap 'rm -rf "${tmp_root}"' EXIT

repo="${tmp_root}/repo"
mkdir -p "${repo}"
cat > "${repo}/mission.md" <<'MISSION'
# Mission

Round 1 fixture mission.
MISSION

cd "${repo}"

assert_fails missing-session-id.json "${RDL}" start research mission.md --session-id
assert_file_contains missing-session-id.json '"status": "error"'
assert_file_contains missing-session-id.json '"code":"missing_session_id"'
assert_file_contains missing-session-id.json '"blockers": \['

assert_fails status-bogus.json "${RDL}" status --bogus
assert_file_contains status-bogus.json '"status": "error"'
assert_file_contains status-bogus.json '"code":"unknown_option"'

"${RDL}" start research mission.md --session-id r1 > start.json
"${RDL}" doctor > doctor-ok.json
assert_file_contains doctor-ok.json '"status": "ok"'
assert_file_contains doctor-ok.json '"action": "doctor"'
assert_file_contains doctor-ok.json '"session_id": "r1"'
assert_file_contains doctor-ok.json '"blockers": \[\]'

rm .rdl/sessions/r1/progress.md
assert_fails doctor-missing.json "${RDL}" doctor
assert_file_contains doctor-missing.json '"status": "blocked"'
assert_file_contains doctor-missing.json '"code":"missing_required_file"'
assert_file_contains doctor-missing.json '"file":"progress.md"'

cp "${ROOT_DIR}/local/research-dev-loop/templates/progress.md" .rdl/sessions/r1/progress.md
printf '{ broken\n' > .rdl/sessions/r1/artifact-manifest.json
assert_fails doctor-bad-manifest.json "${RDL}" doctor
assert_file_contains doctor-bad-manifest.json '"status": "error"'
assert_file_contains doctor-bad-manifest.json '"code":"invalid_artifact_manifest_json"'

cat > .rdl/sessions/r1/artifact-manifest.json <<'JSON'
{
  "artifacts": [
    {
      "id": "A1",
      "kind": "benchmark"
    }
  ]
}
JSON
assert_fails doctor-invalid-artifact.json "${RDL}" doctor
assert_file_contains doctor-invalid-artifact.json '"status": "blocked"'
assert_file_contains doctor-invalid-artifact.json '"code":"invalid_artifact_entry"'

cp "${ROOT_DIR}/local/research-dev-loop/templates/artifact-manifest.json" .rdl/sessions/r1/artifact-manifest.json
printf '{ broken\n' > .rdl/sessions/r1/state.json
assert_fails status-corrupt.json "${RDL}" status
assert_file_contains status-corrupt.json '"status": "error"'
assert_file_contains status-corrupt.json '"code":"corrupted_state"'

repo2="${tmp_root}/repo2"
mkdir -p "${repo2}/.rdl/sessions/bad"
printf '{ broken\n' > "${repo2}/.rdl/sessions/bad/state.json"
cd "${repo2}"
assert_fails doctor-corrupt.json "${RDL}" doctor
assert_file_contains doctor-corrupt.json '"status": "error"'
assert_file_contains doctor-corrupt.json '"code":"corrupted_state"'

echo "round1 tests ok"

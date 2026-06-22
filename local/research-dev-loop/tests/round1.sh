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
assert_file_contains status-corrupt.json '"code":"invalid_state_json"'

repo2="${tmp_root}/repo2"
mkdir -p "${repo2}/.rdl/sessions/bad"
printf '{ broken\n' > "${repo2}/.rdl/sessions/bad/state.json"
cd "${repo2}"
assert_fails doctor-corrupt.json "${RDL}" doctor
assert_file_contains doctor-corrupt.json '"status": "error"'
assert_file_contains doctor-corrupt.json '"code":"invalid_state_json"'

repo3="${tmp_root}/repo3"
mkdir -p "${repo3}/.rdl/sessions/bad"
cat > "${repo3}/.rdl/sessions/bad/state.json" <<'JSON'
{
  "schema_version": 2,
  "session_id": "bad",
  "mode": "research",
  "phase": "plan",
  "round": 1,
  "status": "closed-positive",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cd "${repo3}"
assert_fails doctor-unsupported.json "${RDL}" doctor
assert_file_contains doctor-unsupported.json '"status": "error"'
assert_file_contains doctor-unsupported.json '"code":"unsupported_schema"'

repo4="${tmp_root}/repo4"
mkdir -p "${repo4}/.rdl/sessions/bad"
cat > "${repo4}/.rdl/sessions/bad/state.json" <<'JSON'
{
  "schema_version": 1,
  "session_id": "bad",
  "mode": "research",
  "phase": "plan",
  "round": 1,
  "status": "nonsense",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cd "${repo4}"
assert_fails doctor-invalid-status.json "${RDL}" doctor
assert_file_contains doctor-invalid-status.json '"status": "error"'
assert_file_contains doctor-invalid-status.json '"code":"invalid_status"'

repo5="${tmp_root}/repo5"
mkdir -p "${repo5}/.rdl/sessions/done"
cat > "${repo5}/.rdl/sessions/done/state.json" <<'JSON'
{
  "schema_version": 1,
  "session_id": "done",
  "mode": "research",
  "phase": "complete",
  "round": 1,
  "status": "closed-positive",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cd "${repo5}"
"${RDL}" status > status-closed.json
assert_file_contains status-closed.json '"status": "ok"'
assert_file_contains status-closed.json '"next_action": "rdl start research <mission.md>"'

repo6="${tmp_root}/repo6"
mkdir -p "${repo6}/.rdl/sessions/bad"
cat > "${repo6}/mission.md" <<'MISSION'
# Mission
MISSION
cat > "${repo6}/.rdl/sessions/bad/state.json" <<'JSON'
{
  "schema_version": 2,
  "session_id": "bad",
  "mode": "research",
  "phase": "plan",
  "round": 1,
  "status": "closed-positive",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cd "${repo6}"
assert_fails start-unsupported.json "${RDL}" start research mission.md --session-id new
assert_file_contains start-unsupported.json '"status": "error"'
assert_file_contains start-unsupported.json '"code":"unsupported_schema"'
[[ ! -e .rdl/sessions/new ]] || fail "start created a new session despite unsupported existing schema"

repo7="${tmp_root}/repo7"
mkdir -p "${repo7}/.rdl/sessions/bad"
cat > "${repo7}/mission.md" <<'MISSION'
# Mission
MISSION
cat > "${repo7}/.rdl/sessions/bad/state.json" <<'JSON'
{
  "schema_version": 1,
  "session_id": "bad",
  "mode": "research",
  "phase": "plan",
  "round": 1,
  "status": "nonsense",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cd "${repo7}"
assert_fails start-invalid-status.json "${RDL}" start research mission.md --session-id new
assert_file_contains start-invalid-status.json '"status": "error"'
assert_file_contains start-invalid-status.json '"code":"invalid_status"'
[[ ! -e .rdl/sessions/new ]] || fail "start created a new session despite invalid existing status"

repo8="${tmp_root}/repo8"
mkdir -p "${repo8}/.rdl/sessions/done" "${repo8}/.rdl/sessions/old"
cat > "${repo8}/mission.md" <<'MISSION'
# Mission
MISSION
cat > "${repo8}/.rdl/sessions/done/state.json" <<'JSON'
{
  "schema_version": 1,
  "session_id": "done",
  "mode": "research",
  "phase": "complete",
  "round": 1,
  "status": "closed-positive",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cat > "${repo8}/.rdl/sessions/old/state.json" <<'JSON'
{
  "schema_version": 1,
  "session_id": "old",
  "mode": "build",
  "phase": "complete",
  "round": 1,
  "status": "abandoned",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null
}
JSON
cd "${repo8}"
"${RDL}" start research mission.md --session-id new > start-after-closed.json
assert_file_contains start-after-closed.json '"status": "ok"'
assert_file_contains start-after-closed.json '"session_id": "new"'
[[ -d .rdl/sessions/new ]] || fail "start did not create a new session after valid closed sessions"

repo9="${tmp_root}/repo9"
mkdir -p "${repo9}/.rdl/sessions/bad"
cat > "${repo9}/mission.md" <<'MISSION'
# Mission
MISSION
cd "${repo9}"
assert_fails start-missing-state.json "${RDL}" start research mission.md --session-id new
assert_file_contains start-missing-state.json '"status": "error"'
assert_file_contains start-missing-state.json '"code":"missing_state"'
[[ ! -e .rdl/sessions/new ]] || fail "start created a new session despite missing existing state"

echo "round1 tests ok"

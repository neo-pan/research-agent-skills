#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE_DIR="${SKILL_DIR}/templates"

RDL_DIR=".rdl"
SESSIONS_DIR="${RDL_DIR}/sessions"
FOUND_SESSION_DIR=""

usage() {
  cat <<'EOF'
Usage:
  rdl start research <mission.md> [--session-id <id>] [--json]
  rdl start build <mission-or-plan.md> [--session-id <id>] [--json]
  rdl status [--json]
  rdl doctor [--json]
EOF
}

json_escape() {
  local value="${1-}"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  printf '%s' "${value}"
}

json_array() {
  local first=1
  printf '['
  for item in "$@"; do
    if [[ "${first}" -eq 0 ]]; then
      printf ','
    fi
    first=0
    printf '"%s"' "$(json_escape "${item}")"
  done
  printf ']'
}

blockers_json() {
  local first=1
  printf '['
  while [[ "$#" -gt 0 ]]; do
    local code="$1"
    local file="$2"
    local message="$3"
    local next="$4"
    shift 4

    if [[ "${first}" -eq 0 ]]; then
      printf ','
    fi
    first=0
    printf '{"code":"%s","file":"%s","message":"%s","next_action":"%s"}' \
      "$(json_escape "${code}")" \
      "$(json_escape "${file}")" \
      "$(json_escape "${message}")" \
      "$(json_escape "${next}")"
  done
  printf ']'
}

emit_result() {
  local status="$1"
  local action="$2"
  local session_id="$3"
  local mode="$4"
  local phase="$5"
  local round="$6"
  local next_action="$7"
  shift 7
  local blocker_count="${1:-0}"
  shift
  local blockers=("$@")
  if [[ "${blocker_count}" -ne "${#blockers[@]}" || $((blocker_count % 4)) -ne 0 ]]; then
    blockers=("invalid_result_contract" "" "Internal blocker tuple is malformed." "Fix the RDL command implementation.")
  fi
  local missing=()
  local i=0
  while [[ "${i}" -lt "${#blockers[@]}" ]]; do
    missing+=("${blockers[$((i + 1))]}")
    i=$((i + 4))
  done

  cat <<EOF
{
  "status": "$(json_escape "${status}")",
  "action": "$(json_escape "${action}")",
  "session_id": "$(json_escape "${session_id}")",
  "mode": "$(json_escape "${mode}")",
  "phase": "$(json_escape "${phase}")",
  "round": ${round:-0},
  "missing": $(json_array "${missing[@]}"),
  "warnings": [],
  "blockers": $(blockers_json "${blockers[@]}"),
  "next_action": "$(json_escape "${next_action}")"
}
EOF
}

emit_ok() {
  emit_result "ok" "$1" "$2" "$3" "$4" "$5" "$6" 0
}

emit_problem() {
  local status="$1"
  local action="$2"
  local session_id="$3"
  local mode="$4"
  local phase="$5"
  local round="$6"
  local next_action="$7"
  shift 7
  emit_result "${status}" "${action}" "${session_id}" "${mode}" "${phase}" "${round}" "${next_action}" "$#" "$@"
}

die_result() {
  local action="$1"
  local code="$2"
  local file="$3"
  local message="$4"
  local next_action="$5"
  emit_problem "error" "${action}" "" "" "" 0 "${next_action}" "${code}" "${file}" "${message}" "${next_action}"
  exit 1
}

now_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

session_id_default() {
  date -u +"%Y-%m-%d-%H%M%S"
}

session_dirs() {
  if [[ ! -d "${SESSIONS_DIR}" ]]; then
    return 0
  fi

  find "${SESSIONS_DIR}" -mindepth 1 -maxdepth 1 -type d | sort
}

json_value() {
  local file="$1"
  local key="$2"
  sed -n 's/^[[:space:]]*"'"${key}"'"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${file}" | head -n 1
}

json_number() {
  local file="$1"
  local key="$2"
  sed -n 's/^[[:space:]]*"'"${key}"'"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "${file}" | head -n 1
}

valid_json_file() {
  local file="$1"
  if command -v jq >/dev/null 2>&1; then
    jq empty "${file}" >/dev/null 2>&1
    return $?
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 -m json.tool "${file}" >/dev/null 2>&1
    return $?
  fi
  case "${file}" in
    *.json)
      grep -q '[{}]' "${file}"
      ;;
    *)
      return 1
      ;;
  esac
}

json_artifacts_valid() {
  local file="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -e '
      (.artifacts // []) | type == "array" and
      all(.[]; (.id | type == "string" and length > 0) and
               (.kind | type == "string" and length > 0) and
               (((.path // "") | length > 0) or ((.url // "") | length > 0)))
    ' "${file}" >/dev/null 2>&1
    return $?
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$file" <<'PY' >/dev/null 2>&1
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

artifacts = data.get("artifacts", [])
if not isinstance(artifacts, list):
    raise SystemExit(1)
for artifact in artifacts:
    if not isinstance(artifact, dict):
        raise SystemExit(1)
    if not artifact.get("id") or not artifact.get("kind"):
        raise SystemExit(1)
    if not artifact.get("path") and not artifact.get("url"):
        raise SystemExit(1)
PY
    return $?
  fi

  grep -q '"artifacts"[[:space:]]*:' "${file}"
}

find_session_for_read() {
  local action="$1"
  FOUND_SESSION_DIR=""
  mapfile -t dirs < <(session_dirs)
  if [[ "${#dirs[@]}" -eq 0 ]]; then
    return 1
  fi

  local active=()
  local corrupted=()
  local dir
  for dir in "${dirs[@]}"; do
    local state_file="${dir}/state.json"
    if [[ ! -f "${state_file}" ]]; then
      corrupted+=("${dir}")
      continue
    fi
    if ! valid_json_file "${state_file}"; then
      corrupted+=("${dir}")
      continue
    fi
    if [[ "$(json_value "${state_file}" "status")" == "active" ]]; then
      active+=("${dir}")
    fi
  done

  if [[ "${#corrupted[@]}" -gt 0 ]]; then
    local file="${corrupted[0]}/state.json"
    emit_problem "error" "${action}" "" "" "" 0 "repair or abandon the corrupted RDL session" \
      "corrupted_state" "${file}" "Session state is missing or invalid." "Repair the RDL session metadata or start from a clean session."
    exit 1
  fi

  if [[ "${#active[@]}" -eq 0 ]]; then
    return 1
  fi
  if [[ "${#active[@]}" -gt 1 ]]; then
    emit_problem "error" "${action}" "" "" "" 0 "close or abandon duplicate active sessions" \
      "multiple_active_sessions" "${SESSIONS_DIR}" "More than one active RDL session exists." "Close or abandon all but one active session."
    exit 1
  fi

  FOUND_SESSION_DIR="${active[0]}"
}

render_prompt() {
  local mode="$1"
  local round="$2"
  local objective="$3"
  local previous_decision="$4"
  local target="$5"

  while IFS= read -r line; do
    line="${line//\{\{MODE\}\}/${mode}}"
    line="${line//\{\{ROUND\}\}/${round}}"
    line="${line//\{\{OBJECTIVE\}\}/${objective}}"
    line="${line//\{\{PREVIOUS_DECISION\}\}/${previous_decision}}"
    printf '%s\n' "${line}"
  done < "${TEMPLATE_DIR}/prompt.md" > "${target}"
}

copy_or_template_mission() {
  local source="$1"
  local target="$2"
  if [[ -f "${source}" ]]; then
    cp "${source}" "${target}"
  else
    cp "${TEMPLATE_DIR}/mission.md" "${target}"
  fi
}

cmd_start() {
  local mode="${1-}"
  local mission_file="${2-}"
  if [[ "$#" -lt 2 ]]; then
    die_result "start" "missing_arguments" "" "start requires mode and mission file." "rdl start research <mission.md>"
  fi
  shift 2

  if [[ "${mode}" != "research" && "${mode}" != "build" ]]; then
    die_result "start" "invalid_mode" "" "mode must be research or build." "Use rdl start research or rdl start build."
  fi
  if [[ -z "${mission_file}" ]]; then
    die_result "start" "missing_mission" "" "mission file is required." "Pass a mission or plan file."
  fi
  if [[ ! -f "${mission_file}" ]]; then
    die_result "start" "missing_mission_file" "${mission_file}" "mission file not found: ${mission_file}" "Create the mission file or pass an existing file."
  fi

  local session_id=""
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --session-id)
        if [[ "$#" -lt 2 || -z "${2-}" || "${2-}" == --* ]]; then
          die_result "start" "missing_session_id" "" "--session-id requires a value." "Pass --session-id <id>."
        fi
        session_id="${2-}"
        shift 2
        ;;
      --json)
        shift
        ;;
      *)
        die_result "start" "unknown_option" "" "unknown option: $1" "Run rdl --help."
        ;;
    esac
  done

  local existing_dir=""
  if find_session_for_read start; then
    existing_dir="${FOUND_SESSION_DIR}"
    emit_problem "blocked" "start" "" "" "" 0 "rdl status" \
      "active_session_exists" "${existing_dir}/state.json" "An active RDL session already exists." "Run rdl status, then close or abandon the active session before starting another."
    exit 2
  fi

  if [[ -z "${session_id}" ]]; then
    session_id="$(session_id_default)"
  fi
  if [[ ! "${session_id}" =~ ^[A-Za-z0-9._-]+$ ]]; then
    die_result "start" "invalid_session_id" "" "session id may contain only letters, numbers, dot, underscore, and dash." "Choose a simpler --session-id."
  fi

  local session_dir="${SESSIONS_DIR}/${session_id}"
  if [[ -e "${session_dir}" ]]; then
    emit_problem "blocked" "start" "${session_id}" "" "" 0 "choose a different --session-id" \
      "session_already_exists" "${session_dir}" "A session with this id already exists." "Choose a different --session-id."
    exit 2
  fi

  local tmp_dir="${session_dir}.tmp.$$"
  mkdir -p "${tmp_dir}/rounds/001"

  local created_at
  created_at="$(now_utc)"

  copy_or_template_mission "${mission_file}" "${tmp_dir}/mission.md"
  cp "${TEMPLATE_DIR}/factors.md" "${tmp_dir}/factors.md"
  cp "${TEMPLATE_DIR}/artifact-manifest.json" "${tmp_dir}/artifact-manifest.json"
  cp "${TEMPLATE_DIR}/decision-ledger.md" "${tmp_dir}/decision-ledger.md"
  cp "${TEMPLATE_DIR}/progress.md" "${tmp_dir}/progress.md"
  render_prompt "${mode}" "1" "$(basename "${mission_file}")" "none" "${tmp_dir}/rounds/001/prompt.md"

  cat > "${tmp_dir}/state.json" <<EOF
{
  "schema_version": 1,
  "session_id": "$(json_escape "${session_id}")",
  "mode": "$(json_escape "${mode}")",
  "phase": "plan",
  "round": 1,
  "status": "active",
  "mission_file": "mission.md",
  "guard_session_id": null,
  "last_guard_command_id": null,
  "created_at_utc": "${created_at}",
  "updated_at_utc": "${created_at}"
}
EOF

  cat > "${tmp_dir}/integrity.json" <<EOF
{
  "schema_version": 1,
  "session_id": "$(json_escape "${session_id}")",
  "entries": []
}
EOF

  mkdir -p "${SESSIONS_DIR}"
  mv "${tmp_dir}" "${session_dir}"
  emit_ok "start" "${session_id}" "${mode}" "plan" 1 "${session_dir}/rounds/001/prompt.md"
}

cmd_status() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --json)
        shift
        ;;
      *)
        die_result "status" "unknown_option" "" "unknown option: $1" "Run rdl --help."
        ;;
    esac
  done

  local session_dir
  if ! find_session_for_read status; then
    emit_ok "status" "" "" "" 0 "rdl start research <mission.md>"
    return 0
  fi
  session_dir="${FOUND_SESSION_DIR}"

  local state_file="${session_dir}/state.json"
  local session_id mode phase status round
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  phase="$(json_value "${state_file}" "phase")"
  status="$(json_value "${state_file}" "status")"
  round="$(json_number "${state_file}" "round")"

  emit_ok "status" "${session_id}" "${mode}" "${phase}" "${round}" "${status}"
}

add_blocker() {
  local -n target="$1"
  shift
  target+=("$@")
}

validate_session() {
  local session_dir="$1"
  local -n errors_ref="$2"
  local -n blockers_ref="$3"

  local state_file="${session_dir}/state.json"
  if [[ ! -f "${state_file}" ]]; then
    add_blocker errors_ref "missing_state" "${state_file}" "state.json is missing." "Restore state.json or abandon the session."
    return
  fi
  if ! valid_json_file "${state_file}"; then
    add_blocker errors_ref "invalid_state_json" "${state_file}" "state.json is not valid JSON." "Repair state.json explicitly."
    return
  fi

  local schema session_id mode phase round status mission_file
  schema="$(json_number "${state_file}" "schema_version")"
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  phase="$(json_value "${state_file}" "phase")"
  round="$(json_number "${state_file}" "round")"
  status="$(json_value "${state_file}" "status")"
  mission_file="$(json_value "${state_file}" "mission_file")"

  if [[ "${schema}" != "1" ]]; then
    add_blocker errors_ref "unsupported_schema" "${state_file}" "schema_version must be 1." "Use a supported RDL session or migrate explicitly."
  fi
  if [[ -z "${session_id}" ]]; then
    add_blocker errors_ref "missing_session_id" "${state_file}" "session_id is missing." "Repair state.json explicitly."
  fi
  if [[ "${mode}" != "research" && "${mode}" != "build" ]]; then
    add_blocker errors_ref "invalid_mode" "${state_file}" "mode must be research or build." "Repair state.json explicitly."
  fi
  case "${phase}" in
    plan|work|evidence|interpret|review|decide|complete) ;;
    *) add_blocker errors_ref "invalid_phase" "${state_file}" "phase is unsupported." "Repair state.json explicitly." ;;
  esac
  if [[ -z "${round}" || "${round}" -lt 1 ]]; then
    add_blocker errors_ref "invalid_round" "${state_file}" "round must be a positive number." "Repair state.json explicitly."
  fi
  case "${status}" in
    active|closed-positive|closed-negative|closed-inconclusive|abandoned) ;;
    *) add_blocker errors_ref "invalid_status" "${state_file}" "status is unsupported." "Repair state.json explicitly." ;;
  esac
  if [[ -z "${mission_file}" ]]; then
    add_blocker errors_ref "missing_mission_file_field" "${state_file}" "mission_file is missing." "Repair state.json explicitly."
  elif [[ ! -f "${session_dir}/${mission_file}" ]]; then
    add_blocker blockers_ref "missing_mission_file" "${mission_file}" "mission file does not exist." "Restore the mission file or repair the session."
  fi

  local required=(
    "integrity.json"
    "factors.md"
    "artifact-manifest.json"
    "decision-ledger.md"
    "progress.md"
  )
  local file
  for file in "${required[@]}"; do
    if [[ ! -f "${session_dir}/${file}" ]]; then
      add_blocker blockers_ref "missing_required_file" "${file}" "${file} is missing." "Restore ${file}."
    fi
  done

  local round_dir="${session_dir}/rounds/$(printf '%03d' "${round:-1}")"
  if [[ ! -d "${round_dir}" ]]; then
    add_blocker blockers_ref "missing_round_dir" "rounds/$(printf '%03d' "${round:-1}")" "active round directory is missing." "Restore or repair the active round directory."
  elif [[ ! -f "${round_dir}/prompt.md" ]]; then
    add_blocker blockers_ref "missing_prompt" "rounds/$(printf '%03d' "${round:-1}")/prompt.md" "current round prompt.md is missing." "Regenerate or restore prompt.md."
  fi

  local progress="${session_dir}/progress.md"
  if [[ -f "${progress}" ]]; then
    local section
    for section in "Active" "Completed" "Blocked" "Deferred" "Open Questions"; do
      if ! grep -q "^## ${section}$" "${progress}"; then
        add_blocker blockers_ref "missing_progress_section" "progress.md#${section}" "progress.md is missing section ${section}." "Add the required progress section."
      fi
    done
  fi

  local manifest="${session_dir}/artifact-manifest.json"
  if [[ -f "${manifest}" ]]; then
    if ! valid_json_file "${manifest}"; then
      add_blocker errors_ref "invalid_artifact_manifest_json" "artifact-manifest.json" "artifact-manifest.json is not valid JSON." "Fix artifact-manifest.json."
    elif ! json_artifacts_valid "${manifest}"; then
      add_blocker blockers_ref "invalid_artifact_entry" "artifact-manifest.json" "artifact entries need id, kind, and path or url." "Fix artifact entries or remove invalid artifacts."
    fi
  fi
}

cmd_doctor() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --json)
        shift
        ;;
      *)
        die_result "doctor" "unknown_option" "" "unknown option: $1" "Run rdl --help."
        ;;
    esac
  done

  local session_dir
  if ! find_session_for_read doctor; then
    emit_problem "blocked" "doctor" "" "" "" 0 "rdl start research <mission.md>" \
      "no_active_session" "${SESSIONS_DIR}" "No active RDL session exists." "Start an RDL session."
    return 2
  fi
  session_dir="${FOUND_SESSION_DIR}"

  local state_file="${session_dir}/state.json"
  local session_id mode phase round
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  phase="$(json_value "${state_file}" "phase")"
  round="$(json_number "${state_file}" "round")"

  local errors=()
  local blockers=()
  validate_session "${session_dir}" errors blockers

  if [[ "${#errors[@]}" -gt 0 ]]; then
    emit_problem "error" "doctor" "${session_id}" "${mode}" "${phase}" "${round:-0}" "repair RDL session metadata" "${errors[@]}"
    return 1
  fi
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    emit_problem "blocked" "doctor" "${session_id}" "${mode}" "${phase}" "${round:-0}" "complete missing RDL records" "${blockers[@]}"
    return 2
  fi

  emit_ok "doctor" "${session_id}" "${mode}" "${phase}" "${round:-0}" "rdl review"
}

main() {
  local command="${1-}"
  if [[ -z "${command}" || "${command}" == "-h" || "${command}" == "--help" ]]; then
    usage
    exit 0
  fi
  shift

  case "${command}" in
    start)
      cmd_start "$@"
      ;;
    status)
      cmd_status "$@"
      ;;
    doctor)
      cmd_doctor "$@"
      ;;
    *)
      die_result "unknown" "unknown_command" "" "unknown command: ${command}" "Run rdl --help."
      ;;
  esac
}

main "$@"

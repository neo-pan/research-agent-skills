#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE_DIR="${SKILL_DIR}/templates"

RDL_DIR=".rdl"
SESSIONS_DIR="${RDL_DIR}/sessions"

usage() {
  cat <<'EOF'
Usage:
  rdl start research <mission.md> [--session-id <id>] [--json]
  rdl start build <mission-or-plan.md> [--session-id <id>] [--json]
  rdl status [--json]
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

emit_result() {
  local status="$1"
  local action="$2"
  local session_id="$3"
  local mode="$4"
  local phase="$5"
  local round="$6"
  local next_action="$7"
  shift 7
  local missing=("$@")

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
  "blockers": [],
  "next_action": "$(json_escape "${next_action}")"
}
EOF
}

die_result() {
  local action="$1"
  local message="$2"
  emit_result "error" "${action}" "" "" "" 0 "" "${message}"
  exit 1
}

now_utc() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

session_id_default() {
  date -u +"%Y-%m-%d-%H%M%S"
}

active_sessions() {
  if [[ ! -d "${SESSIONS_DIR}" ]]; then
    return 0
  fi

  find "${SESSIONS_DIR}" -mindepth 2 -maxdepth 2 -name state.json -print0 |
    while IFS= read -r -d '' state_file; do
      if grep -q '"status"[[:space:]]*:[[:space:]]*"active"' "${state_file}"; then
        dirname "${state_file}"
      fi
    done
}

active_session_dir() {
  mapfile -t sessions < <(active_sessions)
  if [[ "${#sessions[@]}" -eq 0 ]]; then
    return 1
  fi
  printf '%s\n' "${sessions[0]}"
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
  shift 2 || true

  if [[ "${mode}" != "research" && "${mode}" != "build" ]]; then
    die_result "start" "mode must be research or build"
  fi
  if [[ -z "${mission_file}" ]]; then
    die_result "start" "mission file is required"
  fi
  if [[ ! -f "${mission_file}" ]]; then
    die_result "start" "mission file not found: ${mission_file}"
  fi

  local session_id=""
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --session-id)
        session_id="${2-}"
        shift 2
        ;;
      --json)
        shift
        ;;
      *)
        die_result "start" "unknown option: $1"
        ;;
    esac
  done

  mapfile -t existing < <(active_sessions)
  if [[ "${#existing[@]}" -gt 0 ]]; then
    emit_result "blocked" "start" "" "" "" 0 "rdl status" "active session already exists"
    exit 2
  fi

  if [[ -z "${session_id}" ]]; then
    session_id="$(session_id_default)"
  fi
  if [[ ! "${session_id}" =~ ^[A-Za-z0-9._-]+$ ]]; then
    die_result "start" "session id may contain only letters, numbers, dot, underscore, and dash"
  fi

  local session_dir="${SESSIONS_DIR}/${session_id}"
  if [[ -e "${session_dir}" ]]; then
    emit_result "blocked" "start" "${session_id}" "" "" 0 "choose a different --session-id" "session already exists"
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
  emit_result "ok" "start" "${session_id}" "${mode}" "plan" 1 "${session_dir}/rounds/001/prompt.md"
}

cmd_status() {
  local session_dir
  if ! session_dir="$(active_session_dir)"; then
    emit_result "ok" "status" "" "" "" 0 "rdl start research <mission.md>"
    return 0
  fi

  local state_file="${session_dir}/state.json"
  local session_id mode phase status round
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  phase="$(json_value "${state_file}" "phase")"
  status="$(json_value "${state_file}" "status")"
  round="$(json_number "${state_file}" "round")"

  emit_result "ok" "status" "${session_id}" "${mode}" "${phase}" "${round}" "${status}"
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
    *)
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"

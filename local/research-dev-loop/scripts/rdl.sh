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
  rdl review [--json]
  rdl decide <decision-type> [--json]
  rdl next [--json]
  rdl close positive|negative|inconclusive [--json]
  rdl abandon <reason> [--json]
  rdl guard-stop [--guard-session-id <id>] [--guard-command-id <id>] [--json]
  rdl repair [--json]
EOF
}

json_escape() {
  local value="${1-}"
  local output=""
  local char=""
  local code=""
  local escaped=""
  while [[ -n "${value}" ]]; do
    char="${value:0:1}"
    value="${value:1}"
    case "${char}" in
      '\')
        output="${output}\\\\"
        ;;
      '"')
        output="${output}\\\""
        ;;
      $'\b')
        output="${output}\\b"
        ;;
      $'\f')
        output="${output}\\f"
        ;;
      $'\n')
        output="${output}\\n"
        ;;
      $'\r')
        output="${output}\\r"
        ;;
      $'\t')
        output="${output}\\t"
        ;;
      *)
        printf -v code '%d' "'${char}"
        if [[ "${code}" -lt 32 ]]; then
          printf -v escaped '\\u%04x' "${code}"
          output="${output}${escaped}"
        else
          output="${output}${char}"
        fi
        ;;
    esac
  done
  printf '%s' "${output}"
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

json_string_value() {
  local file="$1"
  local key="$2"
  if command -v jq >/dev/null 2>&1; then
    jq -r --arg key "${key}" '.[$key] // empty' "${file}"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$file" "$key" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

value = data.get(sys.argv[2], "")
if value is not None:
    print(value)
PY
    return
  fi
  return 1
}

json_number() {
  local file="$1"
  local key="$2"
  sed -n 's/^[[:space:]]*"'"${key}"'"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "${file}" | head -n 1
}

trim() {
  local value="${1-}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "${value}"
}

md_field_value() {
  local file="$1"
  local field="$2"
  local line
  line="$(grep -m 1 "^${field}:" "${file}" || true)"
  trim "${line#*:}"
}

markdown_has_content() {
  local file="$1"
  [[ -f "${file}" ]] || return 1
  awk '
    function flush_pending() {
      if (pending_table != "") {
        if (meaningful_table_row(pending_table)) found = 1
        pending_table = ""
      }
    }
    function trim_cell(value) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      return value
    }
    function is_table_row(line) {
      return line ~ /^[[:space:]]*\|.*\|[[:space:]]*$/
    }
    function is_table_separator(line) {
      return line ~ /^[[:space:]]*\|[[:space:]-]+\|[[:space:]|:-]*$/
    }
    function meaningful_table_row(line, parts, count, i, cell, meaningful) {
      if (!is_table_row(line)) return 0
      if (is_table_separator(line)) return 0
      count = split(line, parts, "|")
      meaningful = 0
      for (i = 2; i < count; i++) {
        cell = trim_cell(parts[i])
        if (cell == "" || cell == "-" || cell == "..." || cell ~ /^(TBD|TODO|N\/A)$/) continue
        if (cell ~ /[[:alnum:]]/) meaningful++
      }
      return meaningful >= 1
    }
    {
      line = $0
      if (is_table_row(line)) {
        if (is_table_separator(line)) {
          pending_table = ""
          next
        }
        flush_pending()
        pending_table = line
        next
      }
      flush_pending()
      if (line ~ /^[[:space:]]*$/) next
      if (line ~ /^[[:space:]]*#/) next
      if (line ~ /^[[:space:]]*<!--/) next
      if (line ~ /^[[:space:]]*(Strong|Moderate|Weak|Contradicted|Inconclusive)[[:space:]]*(\|[[:space:]]*(Strong|Moderate|Weak|Contradicted|Inconclusive)[[:space:]]*)*$/) next
      if (line ~ /[[:alnum:]]/) found = 1
    }
    END {
      flush_pending()
      exit(found ? 0 : 1)
    }
  ' "${file}"
}

markdown_section_has_content() {
  local file="$1"
  local heading_regex="$2"
  awk -v heading="${heading_regex}" '
    function flush_pending() {
      if (pending_table != "") {
        if (meaningful_table_row(pending_table)) found = 1
        pending_table = ""
      }
    }
    function trim_cell(value) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      return value
    }
    function is_table_row(line) {
      return line ~ /^[[:space:]]*\|.*\|[[:space:]]*$/
    }
    function is_table_separator(line) {
      return line ~ /^[[:space:]]*\|[[:space:]-]+\|[[:space:]|:-]*$/
    }
    function meaningful_table_row(line, parts, count, i, cell, meaningful) {
      if (!is_table_row(line)) return 0
      if (is_table_separator(line)) return 0
      count = split(line, parts, "|")
      meaningful = 0
      for (i = 2; i < count; i++) {
        cell = trim_cell(parts[i])
        if (cell == "" || cell == "-" || cell == "..." || cell ~ /^(TBD|TODO|N\/A)$/) continue
        if (cell ~ /[[:alnum:]]/) meaningful++
      }
      return meaningful >= 1
    }
    BEGIN { in_section = 0; found = 0 }
    $0 ~ heading { in_section = 1; pending_table = ""; next }
    in_section && /^##[[:space:]]+/ { flush_pending(); in_section = 0 }
    in_section {
      line = $0
      if (is_table_row(line)) {
        if (is_table_separator(line)) {
          pending_table = ""
          next
        }
        flush_pending()
        pending_table = line
        next
      }
      flush_pending()
      if (line ~ /^[[:space:]]*$/) next
      if (line ~ /^[[:space:]]*#/) next
      if (line ~ /^[[:space:]]*<!--/) next
      if (line ~ /[[:alnum:]]/) found = 1
    }
    END {
      flush_pending()
      exit(found ? 0 : 1)
    }
  ' "${file}"
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
  return 2
}

json_artifacts_valid() {
  local file="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -e '
      (.artifacts // []) | type == "array" and
      all(.[]; (.id | type == "string" and length > 0) and
               (.kind | type == "string" and length > 0) and
               (.round | type == "number" and (. == floor) and . >= 1) and
               (.description | type == "string" and length > 0) and
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
    if not isinstance(artifact.get("round"), int) or artifact["round"] < 1:
        raise SystemExit(1)
    if not artifact.get("description"):
        raise SystemExit(1)
    if not artifact.get("path") and not artifact.get("url"):
        raise SystemExit(1)
PY
    return $?
  fi

  return 2
}

add_json_file_error() {
  local -n target_ref="$1"
  local code="$2"
  local file="$3"
  local invalid_message="$4"
  local invalid_next="$5"
  local missing_message="$6"
  local missing_next="$7"
  local status="$8"

  if [[ "${status}" -eq 2 ]]; then
    add_blocker target_ref "missing_json_tool" "${file}" "${missing_message}" "${missing_next}"
  else
    add_blocker target_ref "${code}" "${file}" "${invalid_message}" "${invalid_next}"
  fi
}

file_sha256() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${file}" | awk '{print $1}'
    return
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${file}" | awk '{print $1}'
    return
  fi
  return 1
}

file_size_bytes() {
  local file="$1"
  wc -c < "${file}" | tr -d '[:space:]'
}

lock_path_for_session() {
  printf '%s/.lock' "$1"
}

lock_owner_alive() {
  local lock_file="$1"
  local pid=""
  if [[ -f "${lock_file}" ]]; then
    pid="$(sed -n 's/^pid=//p' "${lock_file}" | head -n 1)"
  fi
  [[ -n "${pid}" && "${pid}" =~ ^[0-9]+$ ]] || return 1
  kill -0 "${pid}" 2>/dev/null
}

lock_owner_pid() {
  local lock_file="$1"
  sed -n 's/^pid=//p' "${lock_file}" 2>/dev/null | head -n 1
}

validate_session_lock() {
  local session_dir="$1"
  local -n lock_blockers_ref="$2"
  local lock_file
  lock_file="$(lock_path_for_session "${session_dir}")"
  if [[ -n "${RDL_HELD_LOCK:-}" && "${RDL_HELD_LOCK}" == "${lock_file}" ]]; then
    return
  fi
  [[ -f "${lock_file}" ]] || return 0
  if [[ "$(lock_owner_pid "${lock_file}")" == "$$" ]]; then
    return 0
  fi
  if lock_owner_alive "${lock_file}"; then
    add_blocker lock_blockers_ref "session_locked" ".lock" "RDL session is locked by another process." "Wait for the command to finish, then retry."
  else
    add_blocker lock_blockers_ref "stale_lock" ".lock" "RDL session lock exists but the owning process is gone." "Inspect the interrupted command, then run rdl repair or remove .lock manually."
  fi
}

acquire_session_lock() {
  local action="$1"
  local session_dir="$2"
  local session_id="$3"
  local mode="$4"
  local phase="$5"
  local round="$6"
  local lock_file
  lock_file="$(lock_path_for_session "${session_dir}")"
  if ! ( set -o noclobber; printf 'pid=%s\naction=%s\ncreated_at_utc=%s\n' "$$" "${action}" "$(now_utc)" > "${lock_file}" ) 2>/dev/null; then
    local blockers=()
    validate_session_lock "${session_dir}" blockers
    if [[ "${#blockers[@]}" -eq 0 ]]; then
      add_blocker blockers "session_locked" ".lock" "RDL session is locked by another process." "Wait for the command to finish, then retry."
    fi
    emit_problem "blocked" "${action}" "${session_id}" "${mode}" "${phase}" "${round:-0}" "retry after lock clears" "${blockers[@]}"
    return 2
  fi
  RDL_HELD_LOCK="${lock_file}"
}

release_session_lock() {
  if [[ -n "${RDL_HELD_LOCK:-}" && -f "${RDL_HELD_LOCK}" ]]; then
    rm -f "${RDL_HELD_LOCK}"
  fi
  RDL_HELD_LOCK=""
}

repair_stale_session_lock() {
  local session_dir="$1"
  local -n repaired_ref="$2"
  local -n lock_blockers_ref="$3"
  local lock_file
  lock_file="$(lock_path_for_session "${session_dir}")"
  [[ -f "${lock_file}" ]] || return 0

  if lock_owner_alive "${lock_file}"; then
    add_blocker lock_blockers_ref "session_locked" ".lock" "RDL session is locked by another process." "Wait for the command to finish, then retry."
    return 2
  fi

  rm -f "${lock_file}"
  repaired_ref+=(".lock")
}

managed_block_sha256() {
  local file="$1"
  awk '
    /<!-- rdl:managed policy=managed_prefix -->/ {
      if (in_block || seen) exit 2
      in_block = 1
      seen = 1
    }
    in_block { print }
    /<!-- \/rdl:managed -->/ {
      if (in_block) {
        in_block = 0
        closed = 1
      }
    }
    END {
      if (!seen || !closed || in_block) exit 1
    }
  ' "${file}" | file_sha256 -
}

protocol_session_files() {
  printf '%s\n' \
    state.json \
    mission.md \
    factors.md \
    artifact-manifest.json \
    decision-ledger.md \
    progress.md
}

protocol_optional_session_files() {
  printf '%s\n' final-report.md
}

protocol_round_file_names() {
  printf '%s\n' \
    prompt.md \
    intent.md \
    work.md \
    evidence.md \
    interpretation.md \
    review.md \
    decision.md
}

protocol_completed_round_file_names_for_mode() {
  local mode="$1"
  printf '%s\n' prompt.md
  if [[ "${mode}" == "research" ]]; then
    printf '%s\n' evidence.md interpretation.md
  else
    printf '%s\n' intent.md work.md evidence.md
  fi
  printf '%s\n' review.md decision.md
}

protocol_policy_for_path() {
  case "$1" in
    state.json)
      printf 'cli_owned'
      ;;
    decision-ledger.md)
      printf 'append_only'
      ;;
    rounds/*/prompt.md)
      printf 'managed_prefix'
      ;;
    *)
      printf 'human_owned'
      ;;
  esac
}

protocol_path_is_safe_relative() {
  case "$1" in
    ""|/*|.|..|./*|*/.|*/./*|../*|*/..|*/../*)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

protocol_path_known() {
  local path="$1"
  protocol_path_is_safe_relative "${path}" || return 1

  case "${path}" in
    state.json|mission.md|factors.md|artifact-manifest.json|decision-ledger.md|progress.md|final-report.md)
      return 0
      ;;
    rounds/*/prompt.md|rounds/*/intent.md|rounds/*/work.md|rounds/*/evidence.md|rounds/*/interpretation.md|rounds/*/review.md|rounds/*/decision.md)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

protocol_review_required_fields() {
  printf '%s\n' \
    "Reviewer" \
    "Review Mode" \
    "Review Scope" \
    "Artifacts Reviewed" \
    "Verdict" \
    "Decision Reviewed" \
    "Evidence Reviewed" \
    "Blocking Evidence Gaps" \
    "Implementation Findings" \
    "Evaluation Integrity Findings" \
    "Overclaim Risks" \
    "Readiness Level" \
    "Recommended Decision"
}

protocol_decision_required_fields() {
  printf '%s\n' \
    "Decision" \
    "Closes" \
    "Evidence" \
    "Uncertainty" \
    "What this rules out" \
    "What remains unknown" \
    "Recommended next loop" \
    "Next smallest step"
}

protocol_final_report_required_sections() {
  printf '%s\n' \
    "Outcome" \
    "Claim or Capability Closed" \
    "Evidence Cited" \
    "Missing Evidence and Confounders" \
    "Negative, Null, or Inconclusive Results" \
    "Open Questions" \
    "Deferred Items" \
    "Close Checklist"
}

protocol_progress_required_sections() {
  printf '%s\n' \
    "Active" \
    "Completed" \
    "Blocked" \
    "Deferred" \
    "Open Questions"
}

integrity_policy_for_path() {
  protocol_policy_for_path "$1"
}

known_protocol_path() {
  protocol_path_known "$1"
}

session_protocol_files() {
  local session_dir="$1"
  local path
  while IFS= read -r path; do
    if [[ -f "${session_dir}/${path}" ]]; then
      printf '%s\n' "${path}"
    fi
  done < <(protocol_session_files)

  if [[ -d "${session_dir}/rounds" ]]; then
    find "${session_dir}/rounds" -type f \
      \( -name 'prompt.md' -o -name 'intent.md' -o -name 'work.md' -o -name 'evidence.md' -o -name 'interpretation.md' -o -name 'review.md' -o -name 'decision.md' \) \
      | sed "s#^${session_dir}/##" \
      | sort
  fi

  while IFS= read -r path; do
    if [[ -f "${session_dir}/${path}" ]]; then
      printf '%s\n' "${path}"
    fi
  done < <(protocol_optional_session_files)
}

completed_round_protocol_files() {
  local mode="$1"
  local round="$2"
  local round_dir
  round_dir="$(round_path "${round}")"

  local file_name
  while IFS= read -r file_name; do
    printf '%s/%s\n' "${round_dir}" "${file_name}"
  done < <(protocol_completed_round_file_names_for_mode "${mode}")
}

write_integrity_manifest() {
  local session_dir="$1"
  local session_id="$2"
  local tmp_file="${session_dir}/integrity.json.tmp.$$"

  {
    printf '{\n'
    printf '  "schema_version": 1,\n'
    printf '  "session_id": "%s",\n' "$(json_escape "${session_id}")"
    printf '  "entries": [\n'

    local first=1
    local path policy digest size managed_digest
    while IFS= read -r path; do
      [[ -n "${path}" ]] || continue
      digest="$(file_sha256 "${session_dir}/${path}")" || return 1
      policy="$(integrity_policy_for_path "${path}")"
      if [[ "${first}" -eq 0 ]]; then
        printf ',\n'
      fi
      first=0
      printf '    {"path":"%s","policy":"%s","sha256":"%s"' \
        "$(json_escape "${path}")" \
        "$(json_escape "${policy}")" \
        "$(json_escape "${digest}")"
      case "${policy}" in
        append_only)
          size="$(file_size_bytes "${session_dir}/${path}")"
          printf ',"size":%s,"prefix_sha256":"%s"' "${size}" "$(json_escape "${digest}")"
          ;;
        managed_prefix)
          managed_digest="$(managed_block_sha256 "${session_dir}/${path}")" || return 1
          printf ',"managed_sha256":"%s"' "$(json_escape "${managed_digest}")"
          ;;
      esac
      printf '}'
    done < <(session_protocol_files "${session_dir}")

    printf '\n  ]\n'
    printf '}\n'
  } > "${tmp_file}"

  mv "${tmp_file}" "${session_dir}/integrity.json"
}

refresh_integrity_or_error() {
  local action="$1"
  local session_dir="$2"
  local session_id="$3"
  local mode="$4"
  local phase="$5"
  local round="$6"
  if ! write_integrity_manifest "${session_dir}" "${session_id}"; then
    emit_problem "error" "${action}" "${session_id}" "${mode}" "${phase}" "${round:-0}" "install sha256sum or shasum" \
      "missing_hash_tool" "integrity.json" "No sha256 tool is available for integrity manifest refresh." "Install sha256sum or shasum."
    return 1
  fi
}

integrity_entries_valid() {
  local file="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -e '
      .schema_version == 1 and
      (.session_id | type == "string" and length > 0) and
      (.entries | type == "array") and
      all(.entries[];
        (.path | type == "string" and length > 0) and
        (.policy | type == "string" and test("^(cli_owned|append_only|managed_prefix|human_owned)$")) and
        (.sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
        (if .policy == "append_only" then
          (.size | type == "number" and . >= 0) and
          (.prefix_sha256 | type == "string" and test("^[0-9a-f]{64}$"))
        elif .policy == "managed_prefix" then
          (.managed_sha256 | type == "string" and test("^[0-9a-f]{64}$"))
        else
          true
        end)
      )
    ' "${file}" >/dev/null 2>&1
    return $?
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$file" <<'PY' >/dev/null 2>&1
import json
import re
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

if data.get("schema_version") != 1:
    raise SystemExit(1)
if not isinstance(data.get("session_id"), str) or not data["session_id"]:
    raise SystemExit(1)
entries = data.get("entries")
if not isinstance(entries, list):
    raise SystemExit(1)
for entry in entries:
    if not isinstance(entry, dict):
        raise SystemExit(1)
    if not isinstance(entry.get("path"), str) or not entry["path"]:
        raise SystemExit(1)
    if entry.get("policy") not in {"cli_owned", "append_only", "managed_prefix", "human_owned"}:
        raise SystemExit(1)
    if not isinstance(entry.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
        raise SystemExit(1)
    if entry["policy"] == "append_only":
        if not isinstance(entry.get("size"), int) or entry["size"] < 0:
            raise SystemExit(1)
        if not isinstance(entry.get("prefix_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["prefix_sha256"]):
            raise SystemExit(1)
    if entry["policy"] == "managed_prefix":
        if not isinstance(entry.get("managed_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["managed_sha256"]):
            raise SystemExit(1)
PY
    return $?
  fi
  return 1
}

integrity_entries_jsonl() {
  local file="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -c '.entries[]' "${file}"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$file" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

for entry in data.get("entries", []):
    print(json.dumps(entry, separators=(",", ":")))
PY
    return
  fi
  return 1
}

json_entry_field() {
  local entry="$1"
  local field="$2"
  if command -v jq >/dev/null 2>&1; then
    printf '%s' "${entry}" | jq -r --arg field "${field}" '.[$field] // empty'
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import json, sys; print(json.loads(sys.argv[2]).get(sys.argv[1], ""))' "${field}" "${entry}"
    return
  fi
  return 1
}

validate_integrity_completeness() {
  local session_dir="$1"
  local manifest="$2"
  local -n completeness_errors_ref="$3"

  local entries_jsonl
  if ! entries_jsonl="$(integrity_entries_jsonl "${manifest}")"; then
    add_blocker completeness_errors_ref "missing_json_tool" "integrity.json" "No JSON tool is available for integrity validation." "Install jq or python3."
    return
  fi

  declare -A expected_policy=()
  declare -A expected_seen=()
  local expected_path
  while IFS= read -r expected_path; do
    [[ -n "${expected_path}" ]] || continue
    expected_policy["${expected_path}"]="$(integrity_policy_for_path "${expected_path}")"
    expected_seen["${expected_path}"]=0
  done < <(session_protocol_files "${session_dir}")

  if [[ -z "${expected_policy[state.json]+set}" ]]; then
    add_blocker completeness_errors_ref "invalid_integrity_manifest" "integrity.json" "integrity manifest expected set is missing state.json." "Restore state.json or repair session metadata."
    return
  fi

  local entry_count=0
  local entry path policy
  while IFS= read -r entry; do
    path="$(json_entry_field "${entry}" "path")"
    policy="$(json_entry_field "${entry}" "policy")"
    [[ -n "${path}" ]] || continue
    entry_count=$((entry_count + 1))

    if [[ -z "${expected_policy[${path}]+set}" ]]; then
      if [[ ! -f "${session_dir}/${path}" ]]; then
        continue
      fi
      add_blocker completeness_errors_ref "unexpected_integrity_entry" "${path}" "integrity.json contains a path outside the expected RDL protocol set." "Remove the unexpected integrity entry or run rdl repair when available."
      continue
    fi

    expected_seen["${path}"]=$((expected_seen["${path}"] + 1))
    if [[ "${policy}" != "${expected_policy[${path}]}" ]]; then
      add_blocker completeness_errors_ref "integrity_policy_mismatch" "${path}" "integrity entry policy does not match the expected RDL protocol policy." "Restore the expected integrity policy or run rdl repair when available."
    fi
  done <<< "${entries_jsonl}"

  if [[ "${entry_count}" -eq 0 ]]; then
    add_blocker completeness_errors_ref "empty_integrity_manifest" "integrity.json" "integrity.json has no protocol-file entries." "Restore integrity.json or run rdl repair when available."
  fi

  for expected_path in "${!expected_policy[@]}"; do
    case "${expected_seen[${expected_path}]}" in
      0)
        case "${expected_policy[${expected_path}]}" in
          cli_owned|append_only|managed_prefix)
            add_blocker completeness_errors_ref "missing_integrity_entry" "${expected_path}" "integrity.json is missing an expected protected protocol-file entry." "Restore the missing integrity entry or run rdl repair when available."
            ;;
          human_owned)
            ;;
        esac
        ;;
      1)
        ;;
      *)
        add_blocker completeness_errors_ref "duplicate_integrity_entry" "${expected_path}" "integrity.json contains duplicate entries for the same protocol file." "Remove duplicate integrity entries or run rdl repair when available."
        ;;
    esac
  done

  if [[ "${expected_seen[state.json]:-0}" -eq 1 && "${expected_policy[state.json]}" != "cli_owned" ]]; then
    add_blocker completeness_errors_ref "integrity_policy_mismatch" "state.json" "state.json must be protected as cli_owned." "Restore state.json integrity policy or run rdl repair when available."
  fi
}

validate_integrity_manifest() {
  local session_dir="$1"
  local -n integrity_errors_ref="$2"
  local -n integrity_blockers_ref="$3"

  local manifest="${session_dir}/integrity.json"
  if [[ ! -f "${manifest}" ]]; then
    return
  fi
  local json_status=0
  valid_json_file "${manifest}" || json_status=$?
  if [[ "${json_status}" -ne 0 ]]; then
    add_json_file_error integrity_errors_ref "invalid_integrity_json" "integrity.json" \
      "integrity.json is not valid JSON." "Repair integrity.json explicitly." \
      "No JSON parser is available for integrity.json validation." "Install jq or python3." \
      "${json_status}"
    return
  fi
  if ! integrity_entries_valid "${manifest}"; then
    add_blocker integrity_errors_ref "invalid_integrity_manifest" "integrity.json" "integrity.json entries are malformed." "Repair integrity.json explicitly."
    return
  fi
  validate_integrity_completeness "${session_dir}" "${manifest}" integrity_errors_ref

  local entry path policy expected actual recorded_size actual_size prefix_hash managed_hash actual_managed_hash
  while IFS= read -r entry; do
    path="$(json_entry_field "${entry}" "path")"
    policy="$(json_entry_field "${entry}" "policy")"
    expected="$(json_entry_field "${entry}" "sha256")"
    [[ -n "${path}" ]] || continue

    if [[ ! -f "${session_dir}/${path}" ]]; then
      add_blocker integrity_blockers_ref "missing_integrity_file" "${path}" "integrity entry path is missing." "Restore ${path} or run rdl repair when available."
      continue
    fi

    case "${policy}" in
      cli_owned)
        actual="$(file_sha256 "${session_dir}/${path}")" || {
          add_blocker integrity_errors_ref "missing_hash_tool" "${path}" "No sha256 tool is available for integrity validation." "Install sha256sum or shasum."
          continue
        }
        if [[ "${actual}" != "${expected}" ]]; then
          add_blocker integrity_errors_ref "integrity_violation_cli_owned" "${path}" "CLI-owned protocol file hash changed." "Restore ${path} or run rdl repair when available."
        fi
        ;;
      append_only)
        recorded_size="$(json_entry_field "${entry}" "size")"
        prefix_hash="$(json_entry_field "${entry}" "prefix_sha256")"
        actual_size="$(file_size_bytes "${session_dir}/${path}")"
        if [[ "${actual_size}" -lt "${recorded_size}" ]]; then
          add_blocker integrity_errors_ref "integrity_violation_append_only" "${path}" "Append-only protocol file is shorter than its recorded size." "Restore the append-only prefix or run rdl repair when available."
          continue
        fi
        actual="$(head -c "${recorded_size}" "${session_dir}/${path}" | file_sha256 -)" || {
          add_blocker integrity_errors_ref "missing_hash_tool" "${path}" "No sha256 tool is available for append-only integrity validation." "Install sha256sum or shasum."
          continue
        }
        if [[ "${actual}" != "${prefix_hash}" ]]; then
          add_blocker integrity_errors_ref "integrity_violation_append_only" "${path}" "Append-only protocol file prefix changed." "Restore the append-only prefix or run rdl repair when available."
        fi
        ;;
      managed_prefix)
        managed_hash="$(json_entry_field "${entry}" "managed_sha256")"
        if ! actual_managed_hash="$(managed_block_sha256 "${session_dir}/${path}")"; then
          add_blocker integrity_errors_ref "missing_managed_block" "${path}" "Managed-prefix protocol file is missing required managed markers." "Restore the generated managed block or run rdl repair when available."
          continue
        fi
        if [[ "${actual_managed_hash}" != "${managed_hash}" ]]; then
          add_blocker integrity_errors_ref "integrity_violation_managed_prefix" "${path}" "Managed-prefix protocol file block changed." "Restore the generated managed block or run rdl repair when available."
        fi
        ;;
      human_owned)
        ;;
    esac
  done < <(integrity_entries_jsonl "${manifest}") || {
    add_blocker integrity_errors_ref "missing_json_tool" "integrity.json" "No JSON tool is available for integrity validation." "Install jq or python3."
  }
}

validate_repairable_session_structure() {
  local session_dir="$1"
  local -n repair_errors_ref="$2"
  local -n repair_blockers_ref="$3"

  validate_state_file "${session_dir}" repair_errors_ref
  if [[ "${#repair_errors_ref[@]}" -gt 0 ]]; then
    return
  fi

  local state_file="${session_dir}/state.json"
  local round mission_file
  round="$(json_number "${state_file}" "round")"
  mission_file="$(json_value "${state_file}" "mission_file")"

  local required=(
    "${mission_file}"
    "factors.md"
    "artifact-manifest.json"
    "decision-ledger.md"
    "progress.md"
  )
  local file
  for file in "${required[@]}"; do
    if [[ ! -f "${session_dir}/${file}" ]]; then
      add_blocker repair_blockers_ref "unsafe_missing_protocol_file" "${file}" "${file} is missing and cannot be safely repaired." "Restore ${file} from a known-good source."
    fi
  done

  local round_dir="${session_dir}/rounds/$(printf '%03d' "${round:-1}")"
  if [[ ! -d "${round_dir}" ]]; then
    add_blocker repair_blockers_ref "unsafe_missing_round_dir" "rounds/$(printf '%03d' "${round:-1}")" "active round directory is missing and cannot be safely repaired." "Restore the active round directory."
  fi

  local manifest="${session_dir}/artifact-manifest.json"
  if [[ -f "${manifest}" ]]; then
    local json_status=0
    valid_json_file "${manifest}" || json_status=$?
    if [[ "${json_status}" -ne 0 ]]; then
      add_json_file_error repair_errors_ref "invalid_artifact_manifest_json" "artifact-manifest.json" \
        "artifact-manifest.json is not valid JSON." "Fix artifact-manifest.json before repair." \
        "No JSON parser is available for artifact-manifest.json validation." "Install jq or python3." \
        "${json_status}"
    else
      local artifact_status=0
      json_artifacts_valid "${manifest}" || artifact_status=$?
      if [[ "${artifact_status}" -eq 2 ]]; then
        add_blocker repair_errors_ref "missing_json_tool" "artifact-manifest.json" "No JSON parser is available for artifact-manifest.json validation." "Install jq or python3."
      elif [[ "${artifact_status}" -ne 0 ]]; then
        add_blocker repair_blockers_ref "invalid_artifact_entry" "artifact-manifest.json" "artifact entries need id, kind, round, description, and path or url." "Fix artifact entries before repair."
      fi
    fi
  fi
}

manifest_usable_for_repair() {
  local manifest="$1"
  [[ -f "${manifest}" ]] || return 1
  local json_status=0
  valid_json_file "${manifest}" || json_status=$?
  [[ "${json_status}" -eq 0 ]] || return 1
  integrity_entries_valid "${manifest}" || return 1
  [[ -n "$(integrity_entries_jsonl "${manifest}" | head -n 1)" ]] || return 1
  return 0
}

validate_unverified_manifest_repair_scope() {
  local session_dir="$1"
  local -n unverified_errors_ref="$2"
  add_blocker unverified_errors_ref "unsafe_integrity_manifest" "integrity.json" "repair requires a usable integrity manifest before refreshing trusted records." "Restore integrity.json from a trusted source or start a new session."
}

validate_protected_manifest_repair_scope() {
  local session_dir="$1"
  local manifest="$2"
  local -n protected_errors_ref="$3"

  local completeness_errors=()
  validate_integrity_completeness "${session_dir}" "${manifest}" completeness_errors

  local i=0
  local code file message next_action
  while [[ "${i}" -lt "${#completeness_errors[@]}" ]]; do
    code="${completeness_errors[$i]}"
    file="${completeness_errors[$((i + 1))]}"
    message="${completeness_errors[$((i + 2))]}"
    next_action="${completeness_errors[$((i + 3))]}"
    case "${code}" in
      missing_integrity_entry|duplicate_integrity_entry)
        add_blocker protected_errors_ref "${code}" "${file}" "${message}" "${next_action}"
        ;;
      integrity_policy_mismatch)
        case "$(integrity_policy_for_path "${file}")" in
          cli_owned|append_only|managed_prefix)
            add_blocker protected_errors_ref "${code}" "${file}" "${message}" "${next_action}"
            ;;
        esac
        ;;
    esac
    i=$((i + 4))
  done

  declare -A seen_path=()
  local entry path expected_path
  while IFS= read -r entry; do
    path="$(json_entry_field "${entry}" "path")"
    [[ -n "${path}" ]] || continue
    seen_path["${path}"]=1
  done < <(integrity_entries_jsonl "${manifest}")

  local state_file="${session_dir}/state.json"
  local mode round completed_round
  mode="$(json_value "${state_file}" "mode")"
  round="$(json_number "${state_file}" "round")"

  for ((completed_round = 1; completed_round < ${round:-1}; completed_round++)); do
    while IFS= read -r expected_path; do
      [[ -n "${expected_path}" ]] || continue
      [[ -f "${session_dir}/${expected_path}" ]] && continue
      if [[ -z "${seen_path[${expected_path}]+set}" ]]; then
        add_blocker protected_errors_ref "unsafe_missing_protocol_file" "${expected_path}" "Missing prior-round protocol file cannot be safely repaired." "Restore ${expected_path} from a known-good source."
      fi
    done < <(completed_round_protocol_files "${mode}" "${completed_round}")
  done

  while IFS= read -r expected_path; do
    [[ -n "${expected_path}" ]] || continue
    [[ "$(integrity_policy_for_path "${expected_path}")" == "human_owned" ]] || continue
    [[ -f "${session_dir}/${expected_path}" ]] || continue
    if [[ -z "${seen_path[${expected_path}]+set}" ]]; then
      add_blocker protected_errors_ref "missing_integrity_entry" "${expected_path}" "integrity.json is missing an expected human-owned protocol-file entry needed for repair validation." "Restore the missing integrity entry or review the file manually before repair."
    fi
  done < <(session_protocol_files "${session_dir}")
}

plan_prompt_repair() {
  local session_dir="$1"
  local -n repaired_ref="$2"
  local -n prompt_blockers_ref="$3"
  local state_file="${session_dir}/state.json"
  local session_id mode round
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  round="$(json_number "${state_file}" "round")"

  local prompt_path="rounds/$(printf '%03d' "${round:-1}")/prompt.md"
  local prompt_file="${session_dir}/${prompt_path}"
  if [[ -f "${prompt_file}" ]]; then
    return
  fi

  mkdir -p "$(dirname "${prompt_file}")"
  if [[ "${round:-1}" -le 1 ]]; then
    local prompt_objective
    if ! prompt_objective="$(json_string_value "${state_file}" "prompt_objective")" || [[ -z "${prompt_objective}" ]]; then
      add_blocker prompt_blockers_ref "missing_prompt_metadata" "${prompt_path}" "Initial prompt cannot be deterministically repaired without prompt_objective metadata." "Restore ${prompt_path} or start a new session with prompt metadata."
      return
    fi
    render_prompt "${mode}" "${round:-1}" "${prompt_objective}" "none" "${prompt_file}"
  else
    add_blocker prompt_blockers_ref "unsafe_missing_prompt" "${prompt_path}" "Only the initial round prompt can be deterministically repaired." "Restore ${prompt_path} from a known-good source."
    return
  fi
  repaired_ref+=("${prompt_path}")
}

validate_existing_manifest_for_repair() {
  local session_dir="$1"
  local manifest="$2"
  local -n repair_errors_ref="$3"
  local -n repair_blockers_ref="$4"

  if ! manifest_usable_for_repair "${manifest}"; then
    return 0
  fi

  local active_round active_prompt_path
  active_round="$(json_number "${session_dir}/state.json" "round")"
  active_prompt_path="rounds/$(printf '%03d' "${active_round:-1}")/prompt.md"

  local entry path policy expected actual recorded_size actual_size prefix_hash managed_hash actual_managed_hash
  while IFS= read -r entry; do
    path="$(json_entry_field "${entry}" "path")"
    policy="$(json_entry_field "${entry}" "policy")"
    expected="$(json_entry_field "${entry}" "sha256")"
    [[ -n "${path}" ]] || continue

    if ! known_protocol_path "${path}"; then
      add_blocker repair_errors_ref "unsafe_integrity_entry" "${path}" "integrity.json contains a path outside the RDL protocol set." "Remove the unexpected entry manually before repair."
      continue
    fi

    if [[ ! -f "${session_dir}/${path}" ]]; then
      case "${path}" in
        rounds/*/prompt.md)
          if [[ "${path}" != "${active_prompt_path}" ]]; then
            add_blocker repair_errors_ref "unsafe_missing_protocol_file" "${path}" "Missing protocol file cannot be safely repaired." "Restore ${path} from a known-good source."
          fi
          ;;
        *)
          add_blocker repair_errors_ref "unsafe_missing_protocol_file" "${path}" "Missing protocol file cannot be safely repaired." "Restore ${path} from a known-good source."
          ;;
      esac
      continue
    fi

    case "${policy}" in
      cli_owned)
        actual="$(file_sha256 "${session_dir}/${path}")" || {
          add_blocker repair_errors_ref "missing_hash_tool" "${path}" "No sha256 tool is available for repair validation." "Install sha256sum or shasum."
          continue
        }
        if [[ "${actual}" != "${expected}" ]]; then
          add_blocker repair_errors_ref "unsafe_cli_owned_change" "${path}" "CLI-owned protocol file hash changed." "Restore ${path} from a known-good source before repair."
        fi
        ;;
      append_only)
        recorded_size="$(json_entry_field "${entry}" "size")"
        prefix_hash="$(json_entry_field "${entry}" "prefix_sha256")"
        actual_size="$(file_size_bytes "${session_dir}/${path}")"
        if [[ "${actual_size}" -lt "${recorded_size}" ]]; then
          add_blocker repair_errors_ref "unsafe_append_only_change" "${path}" "Append-only protocol file is shorter than its recorded size." "Restore the append-only history before repair."
          continue
        fi
        actual="$(head -c "${recorded_size}" "${session_dir}/${path}" | file_sha256 -)" || {
          add_blocker repair_errors_ref "missing_hash_tool" "${path}" "No sha256 tool is available for repair validation." "Install sha256sum or shasum."
          continue
        }
        if [[ "${actual}" != "${prefix_hash}" ]]; then
          add_blocker repair_errors_ref "unsafe_append_only_change" "${path}" "Append-only protocol file prefix changed." "Restore the append-only history before repair."
        fi
        ;;
      managed_prefix)
        managed_hash="$(json_entry_field "${entry}" "managed_sha256")"
        if ! actual_managed_hash="$(managed_block_sha256 "${session_dir}/${path}")"; then
          add_blocker repair_errors_ref "unsafe_managed_prefix_change" "${path}" "Managed-prefix protocol file is missing managed markers." "Restore the managed block before repair."
          continue
        fi
        if [[ "${actual_managed_hash}" != "${managed_hash}" ]]; then
          add_blocker repair_errors_ref "unsafe_managed_prefix_change" "${path}" "Managed-prefix protocol file block changed." "Restore the generated managed block before repair."
        fi
        ;;
      human_owned)
        actual="$(file_sha256 "${session_dir}/${path}")" || {
          add_blocker repair_errors_ref "missing_hash_tool" "${path}" "No sha256 tool is available for repair validation." "Install sha256sum or shasum."
          continue
        }
        if [[ "${actual}" != "${expected}" ]]; then
          add_blocker repair_errors_ref "unsafe_human_owned_change" "${path}" "Human-owned protocol file hash changed." "Review or restore ${path}; repair will not bless changed human-authored content."
        fi
        ;;
      *)
        add_blocker repair_errors_ref "unsafe_integrity_entry" "${path}" "integrity entry policy is unsupported." "Fix integrity.json before repair."
        ;;
    esac
  done < <(integrity_entries_jsonl "${manifest}") || {
    add_blocker repair_errors_ref "missing_json_tool" "integrity.json" "No JSON tool is available for repair validation." "Install jq or python3."
  }
}

find_active_session_for_start() {
  local action="$1"
  FOUND_SESSION_DIR=""
  mapfile -t dirs < <(session_dirs)
  if [[ "${#dirs[@]}" -eq 0 ]]; then
    return 1
  fi

  local active=()
  local dir
  for dir in "${dirs[@]}"; do
    local state_file="${dir}/state.json"
    local errors=()
    validate_state_file "${dir}" errors
    if [[ "${#errors[@]}" -gt 0 ]]; then
      local session_id="" mode="" phase="" round=""
      if [[ -f "${state_file}" ]]; then
        local json_status=0
        valid_json_file "${state_file}" || json_status=$?
        if [[ "${json_status}" -eq 0 ]]; then
          session_id="$(json_value "${state_file}" "session_id")"
          mode="$(json_value "${state_file}" "mode")"
          phase="$(json_value "${state_file}" "phase")"
          round="$(json_number "${state_file}" "round")"
        fi
      fi
      emit_problem "error" "${action}" "${session_id}" "${mode}" "${phase}" "${round:-0}" "repair RDL session metadata" "${errors[@]}"
      exit 1
    fi
    if [[ "$(json_value "${state_file}" "status")" == "active" ]]; then
      active+=("${dir}")
    fi
  done

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

find_session_for_audit() {
  local action="$1"
  FOUND_SESSION_DIR=""
  mapfile -t dirs < <(session_dirs)
  if [[ "${#dirs[@]}" -eq 0 ]]; then
    return 1
  fi

  local active=()
  local dir
  for dir in "${dirs[@]}"; do
    local state_file="${dir}/state.json"
    local errors=()
    validate_state_file "${dir}" errors
    if [[ "${#errors[@]}" -gt 0 ]]; then
      local session_id="" mode="" phase="" round=""
      if [[ -f "${state_file}" ]]; then
        local json_status=0
        valid_json_file "${state_file}" || json_status=$?
        if [[ "${json_status}" -eq 0 ]]; then
          session_id="$(json_value "${state_file}" "session_id")"
          mode="$(json_value "${state_file}" "mode")"
          phase="$(json_value "${state_file}" "phase")"
          round="$(json_number "${state_file}" "round")"
        fi
      fi
      local next_action="repair RDL session metadata"
      if [[ "${action}" == "guard-stop" ]]; then
        next_action="block"
      fi
      emit_problem "error" "${action}" "${session_id}" "${mode}" "${phase}" "${round:-0}" "${next_action}" "${errors[@]}"
      exit 1
    fi

    local status
    status="$(json_value "${state_file}" "status")"
    if [[ "${status}" == "active" ]]; then
      active+=("${dir}")
    fi
  done

  if [[ "${#active[@]}" -gt 1 ]]; then
    local next_action="close or abandon duplicate active sessions"
    if [[ "${action}" == "guard-stop" ]]; then
      next_action="block"
    fi
    emit_problem "error" "${action}" "" "" "" 0 "${next_action}" \
      "multiple_active_sessions" "${SESSIONS_DIR}" "More than one active RDL session exists." "Close or abandon all but one active session."
    exit 1
  fi
  if [[ "${#active[@]}" -eq 1 ]]; then
    FOUND_SESSION_DIR="${active[0]}"
    return 0
  fi

  return 1
}

render_prompt() {
  local mode="$1"
  local round="$2"
  local objective="$3"
  local previous_decision="$4"
  local target="$5"
  local required_files expected_exit_decision
  if [[ "${mode}" == "research" ]]; then
    required_files="prompt.md, evidence.md, interpretation.md, review.md, decision.md"
    expected_exit_decision="claim decision with evidence and uncertainty"
  else
    required_files="prompt.md, intent.md, work.md, evidence.md, review.md, decision.md"
    expected_exit_decision="capability decision with verification evidence"
  fi

  while IFS= read -r line; do
    line="${line//\{\{MODE\}\}/${mode}}"
    line="${line//\{\{ROUND\}\}/${round}}"
    line="${line//\{\{OBJECTIVE\}\}/${objective}}"
    line="${line//\{\{PREVIOUS_DECISION\}\}/${previous_decision}}"
    line="${line//\{\{REQUIRED_FILES\}\}/${required_files}}"
    line="${line//\{\{EXPECTED_EXIT_DECISION\}\}/${expected_exit_decision}}"
    printf '%s\n' "${line}"
  done < "${TEMPLATE_DIR}/prompt.md" > "${target}"
}

round_path() {
  printf 'rounds/%03d' "$1"
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

load_active_session() {
  local action="$1"
  if ! find_session_for_audit "${action}"; then
    emit_problem "blocked" "${action}" "" "" "" 0 "rdl start research <mission.md>" \
      "no_active_session" "${SESSIONS_DIR}" "No active RDL session exists." "Start an RDL session."
    return 2
  fi
  return 0
}

validate_active_session() {
  local action="$1"
  local session_dir="$2"
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
    emit_problem "error" "${action}" "${session_id}" "${mode}" "${phase}" "${round:-0}" "repair RDL session metadata" "${errors[@]}"
    return 1
  fi
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    emit_problem "blocked" "${action}" "${session_id}" "${mode}" "${phase}" "${round:-0}" "complete missing RDL records" "${blockers[@]}"
    return 2
  fi
  return 0
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
  if find_active_session_for_start start; then
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

  local created_at prompt_objective
  created_at="$(now_utc)"
  prompt_objective="$(basename "${mission_file}")"

  copy_or_template_mission "${mission_file}" "${tmp_dir}/mission.md"
  cp "${TEMPLATE_DIR}/factors.md" "${tmp_dir}/factors.md"
  cp "${TEMPLATE_DIR}/artifact-manifest.json" "${tmp_dir}/artifact-manifest.json"
  cp "${TEMPLATE_DIR}/decision-ledger.md" "${tmp_dir}/decision-ledger.md"
  cp "${TEMPLATE_DIR}/progress.md" "${tmp_dir}/progress.md"
  render_prompt "${mode}" "1" "${prompt_objective}" "none" "${tmp_dir}/rounds/001/prompt.md"

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
  "prompt_objective": "$(json_escape "${prompt_objective}")",
  "created_at_utc": "${created_at}",
  "updated_at_utc": "${created_at}"
}
EOF

  if ! write_integrity_manifest "${tmp_dir}" "${session_id}"; then
    rm -rf "${tmp_dir}"
    die_result "start" "missing_hash_tool" "integrity.json" "No sha256 tool is available for integrity manifest creation." "Install sha256sum or shasum."
  fi

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
  if ! find_session_for_audit status; then
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

validate_state_file() {
  local session_dir="$1"
  local -n state_errors_ref="$2"

  local state_file="${session_dir}/state.json"
  if [[ ! -f "${state_file}" ]]; then
    add_blocker state_errors_ref "missing_state" "${state_file}" "state.json is missing." "Restore state.json or abandon the session."
    return 0
  fi
  local json_status=0
  valid_json_file "${state_file}" || json_status=$?
  if [[ "${json_status}" -ne 0 ]]; then
    add_json_file_error state_errors_ref "invalid_state_json" "${state_file}" \
      "state.json is not valid JSON." "Repair state.json explicitly." \
      "No JSON parser is available for state.json validation." "Install jq or python3." \
      "${json_status}"
    return 0
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
    add_blocker state_errors_ref "unsupported_schema" "${state_file}" "schema_version must be 1." "Use a supported RDL session or migrate explicitly."
  fi
  if [[ -z "${session_id}" ]]; then
    add_blocker state_errors_ref "missing_session_id" "${state_file}" "session_id is missing." "Repair state.json explicitly."
  fi
  if [[ "${mode}" != "research" && "${mode}" != "build" ]]; then
    add_blocker state_errors_ref "invalid_mode" "${state_file}" "mode must be research or build." "Repair state.json explicitly."
  fi
  case "${phase}" in
    plan|work|evidence|interpret|review|decide|complete) ;;
    *) add_blocker state_errors_ref "invalid_phase" "${state_file}" "phase is unsupported." "Repair state.json explicitly." ;;
  esac
  if [[ -z "${round}" || "${round}" -lt 1 ]]; then
    add_blocker state_errors_ref "invalid_round" "${state_file}" "round must be a positive number." "Repair state.json explicitly."
  fi
  case "${status}" in
    active|closed-positive|closed-negative|closed-inconclusive|abandoned) ;;
    *) add_blocker state_errors_ref "invalid_status" "${state_file}" "status is unsupported." "Repair state.json explicitly." ;;
  esac
  if [[ -z "${mission_file}" ]]; then
    add_blocker state_errors_ref "missing_mission_file_field" "${state_file}" "mission_file is missing." "Repair state.json explicitly."
  fi
}

validate_session() {
  local session_dir="$1"
  local -n errors_ref="$2"
  local -n blockers_ref="$3"

  local state_file="${session_dir}/state.json"
  validate_state_file "${session_dir}" errors_ref
  if [[ "${#errors_ref[@]}" -gt 0 ]]; then
    return 0
  fi

  local round mission_file
  round="$(json_number "${state_file}" "round")"
  mission_file="$(json_value "${state_file}" "mission_file")"

  validate_session_lock "${session_dir}" blockers_ref

  if [[ ! -f "${session_dir}/${mission_file}" ]]; then
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

  validate_integrity_manifest "${session_dir}" errors_ref blockers_ref

  local round_dir="${session_dir}/rounds/$(printf '%03d' "${round:-1}")"
  if [[ ! -d "${round_dir}" ]]; then
    add_blocker blockers_ref "missing_round_dir" "rounds/$(printf '%03d' "${round:-1}")" "active round directory is missing." "Restore or repair the active round directory."
  elif [[ ! -f "${round_dir}/prompt.md" ]]; then
    add_blocker blockers_ref "missing_prompt" "rounds/$(printf '%03d' "${round:-1}")/prompt.md" "current round prompt.md is missing." "Regenerate or restore prompt.md."
  fi

  local progress="${session_dir}/progress.md"
  if [[ -f "${progress}" ]]; then
    local section
    while IFS= read -r section; do
      if ! grep -q "^## ${section}$" "${progress}"; then
        add_blocker blockers_ref "missing_progress_section" "progress.md#${section}" "progress.md is missing section ${section}." "Add the required progress section."
      fi
    done < <(protocol_progress_required_sections)
  fi

  local manifest="${session_dir}/artifact-manifest.json"
  if [[ -f "${manifest}" ]]; then
    local json_status=0
    valid_json_file "${manifest}" || json_status=$?
    if [[ "${json_status}" -ne 0 ]]; then
      add_json_file_error errors_ref "invalid_artifact_manifest_json" "artifact-manifest.json" \
        "artifact-manifest.json is not valid JSON." "Fix artifact-manifest.json." \
        "No JSON parser is available for artifact-manifest.json validation." "Install jq or python3." \
        "${json_status}"
    else
      local artifact_status=0
      json_artifacts_valid "${manifest}" || artifact_status=$?
      if [[ "${artifact_status}" -eq 2 ]]; then
        add_blocker errors_ref "missing_json_tool" "artifact-manifest.json" "No JSON parser is available for artifact-manifest.json validation." "Install jq or python3."
      elif [[ "${artifact_status}" -ne 0 ]]; then
        add_blocker blockers_ref "invalid_artifact_entry" "artifact-manifest.json" "artifact entries need id, kind, round, description, and path or url." "Fix artifact entries or remove invalid artifacts."
      fi
    fi
  fi
}

validate_current_round_record() {
  local session_dir="$1"
  local mode="$2"
  local round="$3"
  local -n round_blockers_ref="$4"

  local round_dir="${session_dir}/$(round_path "${round}")"
  local expected_closes
  expected_closes="$(expected_closes_for_mode "${mode}")"

  validate_review_file "${round_dir}/review.md" round_blockers_ref
  validate_decision_file "${round_dir}/decision.md" "${expected_closes}" round_blockers_ref
  validate_mode_round_minimums "${mode}" "${round_dir}" round_blockers_ref
  validate_round_evidence_discipline "${round_dir}" round_blockers_ref
  validate_close_artifact_citations "${session_dir}" "${round_dir}" round_blockers_ref

  local decision=""
  if [[ -f "${round_dir}/decision.md" ]]; then
    decision="$(md_field_value "${round_dir}/decision.md" "Decision")"
  fi
  case "${decision}" in
    close-positive)
      validate_close_readiness "${session_dir}" "${round_dir}" "${round}" "positive" round_blockers_ref
      ;;
    close-negative)
      validate_close_readiness "${session_dir}" "${round_dir}" "${round}" "negative" round_blockers_ref
      ;;
    close-inconclusive)
      validate_close_readiness "${session_dir}" "${round_dir}" "${round}" "inconclusive" round_blockers_ref
      ;;
  esac
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
  if ! find_session_for_audit doctor; then
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
  if [[ "${#errors[@]}" -eq 0 && "${#blockers[@]}" -eq 0 ]]; then
    validate_current_round_record "${session_dir}" "${mode}" "${round:-1}" blockers
  fi

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

valid_decision_type() {
  case "$1" in
    continue|pivot|narrow|broaden|diagnose|build|profile|rerun|accept|reject|close-positive|close-negative|close-inconclusive)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

validate_review_file() {
  local file="$1"
  local -n blockers_ref="$2"
  if [[ ! -f "${file}" ]]; then
    add_blocker blockers_ref "missing_review" "${file}" "review.md is missing." "Run rdl review and complete the review record."
    return 0
  fi

  local field value
  while IFS= read -r field; do
    value="$(md_field_value "${file}" "${field}")"
    if [[ -z "${value}" || "${value}" == *"|"* ]]; then
      add_blocker blockers_ref "missing_review_field" "${file}#${field}" "${field} is missing or still a placeholder." "Complete ${field} in review.md."
    fi
  done < <(protocol_review_required_fields)

  value="$(md_field_value "${file}" "Review Mode")"
  case "${value}" in
    manual|checklist|phase-review|subagent|project-adapter) ;;
    *) add_blocker blockers_ref "invalid_review_mode" "${file}#Review Mode" "Review Mode is unsupported." "Use manual, checklist, phase-review, subagent, or project-adapter." ;;
  esac

  value="$(md_field_value "${file}" "Verdict")"
  case "${value}" in
    PASS|PASS_WITH_NOTES|BLOCKED|INCONCLUSIVE) ;;
    *) add_blocker blockers_ref "invalid_review_verdict" "${file}#Verdict" "Verdict is unsupported." "Use PASS, PASS_WITH_NOTES, BLOCKED, or INCONCLUSIVE." ;;
  esac
}

validate_review_decision_alignment() {
  local review_file="$1"
  local decision_file="$2"
  local -n blockers_ref="$3"
  [[ -f "${review_file}" ]] || return 0

  local verdict decision gaps normalized_gaps
  verdict="$(md_field_value "${review_file}" "Verdict")"
  if [[ -f "${decision_file}" ]]; then
    decision="$(md_field_value "${decision_file}" "Decision")"
  else
    decision=""
  fi
  gaps="$(md_field_value "${review_file}" "Blocking Evidence Gaps")"
  normalized_gaps="$(trim "${gaps}")"
  normalized_gaps="${normalized_gaps,,}"

  if [[ "${verdict}" == "BLOCKED" ]]; then
    add_blocker blockers_ref "blocking_review_verdict" "${review_file}#Verdict" "Review verdict is BLOCKED." "Resolve the review findings before advancing."
  elif [[ "${verdict}" == "INCONCLUSIVE" && "${decision}" != "close-inconclusive" ]]; then
    add_blocker blockers_ref "inconclusive_review_verdict" "${review_file}#Verdict" "Review verdict is INCONCLUSIVE but the decision is not close-inconclusive." "Close inconclusive or complete enough review evidence to proceed."
  fi

  case "${normalized_gaps}" in
    ""|none|"no blocking gaps"|"no blocking evidence gaps"|"n/a"|"not applicable")
      ;;
    *)
      if [[ "${decision}" != "close-inconclusive" ]]; then
        add_blocker blockers_ref "blocking_evidence_gaps" "${review_file}#Blocking Evidence Gaps" "Review records blocking evidence gaps." "Resolve the gaps or close inconclusive."
      fi
      ;;
  esac
}

validate_decision_file() {
  local file="$1"
  local expected_closes="$2"
  local -n blockers_ref="$3"
  if [[ ! -f "${file}" ]]; then
    add_blocker blockers_ref "missing_decision" "${file}" "decision.md is missing." "Run rdl decide <decision-type> and complete the decision record."
    return 0
  fi

  local decision closes next_loop field value
  while IFS= read -r field; do
    value="$(md_field_value "${file}" "${field}")"
    if [[ -z "${value}" || "${value}" == *"|"* ]]; then
      add_blocker blockers_ref "missing_decision_field" "${file}#${field}" "${field} is missing or still a placeholder." "Complete ${field} in decision.md."
    fi
  done < <(protocol_decision_required_fields)

  decision="$(md_field_value "${file}" "Decision")"
  if ! valid_decision_type "${decision}"; then
    add_blocker blockers_ref "invalid_decision_type" "${file}#Decision" "Decision type is unsupported." "Use a planned RDL decision type."
  fi

  closes="$(md_field_value "${file}" "Closes")"
  if [[ "${closes}" != "${expected_closes}" ]]; then
    add_blocker blockers_ref "invalid_closes" "${file}#Closes" "Closes must be ${expected_closes} for this session mode." "Set Closes: ${expected_closes}."
  fi

  next_loop="$(md_field_value "${file}" "Recommended next loop")"
  case "${next_loop}" in
    research|build|none) ;;
    *) add_blocker blockers_ref "invalid_recommended_next_loop" "${file}#Recommended next loop" "Recommended next loop is unsupported." "Use research, build, or none." ;;
  esac
}

validate_build_verification_evidence() {
  local round_dir="$1"
  local -n verification_blockers_ref="$2"
  local evidence_file="${round_dir}/evidence.md"

  if [[ ! -f "${evidence_file}" ]]; then
    add_blocker verification_blockers_ref "missing_verification_evidence" "${evidence_file}" "Build rounds require evidence.md with verification evidence for the capability." "Add verification evidence before running rdl next."
    return 0
  fi

  local label_value
  label_value="$(sed -n 's/^[[:space:]]*Verification evidence:[[:space:]]*\(.*[[:alnum:]].*\)$/\1/Ip' "${evidence_file}" | head -n 1)"
  if [[ -n "${label_value}" ]]; then
    return
  fi

  if ! markdown_section_has_content "${evidence_file}" '^[[:space:]]*##[[:space:]]+Verification Evidence[[:space:]]*$'; then
    add_blocker verification_blockers_ref "missing_verification_evidence" "${evidence_file}" "Build evidence must explicitly identify verification evidence." "Record verification evidence in evidence.md."
  fi
}

validate_round_file_content() {
  local round_dir="$1"
  local file_name="$2"
  local code="$3"
  local message="$4"
  local next_action="$5"
  local -n file_blockers_ref="$6"
  local file="${round_dir}/${file_name}"

  if [[ ! -f "${file}" ]]; then
    add_blocker file_blockers_ref "${code}" "${file}" "${message}" "${next_action}"
    return 0
  fi
  if ! markdown_has_content "${file}"; then
    add_blocker file_blockers_ref "${code}" "${file}" "${message}" "${next_action}"
  fi
}

validate_mode_round_minimums() {
  local mode="$1"
  local round_dir="$2"
  local -n mode_blockers_ref="$3"

  if [[ "${mode}" == "research" ]]; then
    validate_round_file_content "${round_dir}" "evidence.md" "missing_research_evidence" "Research rounds require evidence.md with non-placeholder evidence." "Record research evidence before running rdl next." mode_blockers_ref
    validate_round_file_content "${round_dir}" "interpretation.md" "missing_interpretation" "Research rounds require interpretation.md with non-placeholder interpretation." "Record interpretation before running rdl next." mode_blockers_ref
  else
    validate_round_file_content "${round_dir}" "intent.md" "missing_build_intent" "Build rounds require intent.md with non-placeholder intent." "Record build intent before running rdl next." mode_blockers_ref
    validate_round_file_content "${round_dir}" "work.md" "missing_build_work" "Build rounds require work.md with non-placeholder work." "Record build work before running rdl next." mode_blockers_ref
    validate_build_verification_evidence "${round_dir}" mode_blockers_ref
  fi
}

valid_close_outcome() {
  case "$1" in
    positive|negative|inconclusive)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

validate_final_report() {
  local session_dir="$1"
  local outcome="$2"
  local -n report_blockers_ref="$3"
  local report_file="${session_dir}/final-report.md"

  if [[ ! -f "${report_file}" ]]; then
    add_blocker report_blockers_ref "missing_final_report" "${report_file}" "final-report.md is required before closing a session." "Create final-report.md from the template and complete the close record."
    return
  fi

  local section
  while IFS= read -r section; do
    if ! markdown_section_has_content "${report_file}" "^[[:space:]]*##[[:space:]]+${section}[[:space:]]*$"; then
      add_blocker report_blockers_ref "missing_final_report_section" "${report_file}#${section}" "${section} is missing or still a placeholder." "Complete ${section} in final-report.md."
    fi
  done < <(protocol_final_report_required_sections)

  if grep -q '^[[:space:]]*-[[:space:]]*\[[[:space:]]\]' "${report_file}"; then
    add_blocker report_blockers_ref "incomplete_close_checklist" "${report_file}#Close Checklist" "Close checklist still has unchecked items." "Check every close checklist item that is true for this close record."
  fi

  local recorded_outcome normalized_recorded expected_status
  recorded_outcome="$(awk '
    function trim(value) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      return value
    }
    /^[[:space:]]*##[[:space:]]+Outcome[[:space:]]*$/ { in_section = 1; next }
    in_section && /^##[[:space:]]+/ { exit }
    in_section {
      line = trim($0)
      if (line == "" || line ~ /^<!--/) next
      print line
      exit
    }
  ' "${report_file}")"
  normalized_recorded="$(trim "${recorded_outcome}")"
  normalized_recorded="${normalized_recorded,,}"
  case "${normalized_recorded}" in
    positive|negative|inconclusive)
      normalized_recorded="closed-${normalized_recorded}"
      ;;
  esac
  expected_status="closed-${outcome}"
  if [[ "${normalized_recorded}" != "${expected_status}" ]]; then
    add_blocker report_blockers_ref "close_outcome_mismatch" "${report_file}#Outcome" "Final report outcome must match ${outcome}." "Update final-report.md Outcome or run rdl close with the recorded outcome."
  fi
}

artifact_manifest_ids() {
  local manifest="$1"
  if command -v jq >/dev/null 2>&1; then
    jq -r '(.artifacts // [])[]? | .id // empty' "${manifest}" 2>/dev/null
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - "${manifest}" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as fh:
    data = json.load(fh)

for artifact in data.get("artifacts", []):
    artifact_id = artifact.get("id")
    if artifact_id:
        print(artifact_id)
PY
    return
  fi
  sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${manifest}"
}

extract_id_tokens() {
  grep -Eo '`?[A-Z][A-Z0-9]*-?[0-9][A-Z0-9-]*`?' | tr -d '`' | sort -u || true
}

markdown_section_content() {
  local file="$1"
  local heading_regex="$2"
  awk -v heading="${heading_regex}" '
    $0 ~ heading { in_section = 1; next }
    in_section && /^##[[:space:]]+/ { exit }
    in_section { print }
  ' "${file}"
}

validate_close_artifact_citations() {
  local session_dir="$1"
  local round_dir="$2"
  local -n citation_target_ref="$3"
  local manifest_file="${session_dir}/artifact-manifest.json"
  local decision_file="${round_dir}/decision.md"
  local evidence_file="${round_dir}/evidence.md"
  local report_file="${session_dir}/final-report.md"

  [[ -f "${manifest_file}" ]] || return 0

  declare -A manifest_ids=()
  local id
  while IFS= read -r id; do
    [[ -n "${id}" ]] && manifest_ids["${id}"]=1
  done < <(artifact_manifest_ids "${manifest_file}")

  local ids=()
  if [[ -f "${decision_file}" ]]; then
    mapfile -t ids < <(printf '%s\n' "$(md_field_value "${decision_file}" "Evidence")" | extract_id_tokens)
    for id in "${ids[@]}"; do
      if [[ -n "${id}" && -z "${manifest_ids[${id}]+present}" ]]; then
        add_blocker citation_target_ref "missing_artifact_citation" "${manifest_file}#${id}" "${decision_file}#Evidence cites artifact ID ${id}, but artifact-manifest.json has no matching artifact." "Add ${id} to artifact-manifest.json or remove the citation."
      fi
    done
  fi

  if [[ -f "${evidence_file}" ]]; then
    mapfile -t ids < <(markdown_section_content "${evidence_file}" '^[[:space:]]*##[[:space:]]+Evidence Artifacts[[:space:]]*$' | extract_id_tokens)
    for id in "${ids[@]}"; do
      if [[ -n "${id}" && -z "${manifest_ids[${id}]+present}" ]]; then
        add_blocker citation_target_ref "missing_artifact_citation" "${manifest_file}#${id}" "${evidence_file}#Evidence Artifacts cites artifact ID ${id}, but artifact-manifest.json has no matching artifact." "Add ${id} to artifact-manifest.json or remove the citation."
      fi
    done
  fi

  if [[ -f "${report_file}" ]]; then
    mapfile -t ids < <(markdown_section_content "${report_file}" '^[[:space:]]*##[[:space:]]+Evidence Cited[[:space:]]*$' | extract_id_tokens)
    for id in "${ids[@]}"; do
      if [[ -n "${id}" && -z "${manifest_ids[${id}]+present}" ]]; then
        add_blocker citation_target_ref "missing_artifact_citation" "${manifest_file}#${id}" "${report_file}#Evidence Cited cites artifact ID ${id}, but artifact-manifest.json has no matching artifact." "Add ${id} to artifact-manifest.json or remove the citation."
      fi
    done
  fi
}

validate_close_evidence_discipline() {
  local round_dir="$1"
  local -n evidence_blockers_ref="$2"
  local evidence_file="${round_dir}/evidence.md"

  if [[ ! -f "${evidence_file}" ]]; then
    add_blocker evidence_blockers_ref "missing_close_evidence" "${evidence_file}" "Closing requires current-round evidence.md." "Create evidence.md and record close evidence discipline."
    return 0
  fi

  if ! markdown_section_has_content "${evidence_file}" '^[[:space:]]*##[[:space:]]+Missing Evidence[[:space:]]*$'; then
    add_blocker evidence_blockers_ref "missing_evidence_discipline" "${evidence_file}#Missing Evidence" "Missing Evidence must be recorded before closing." "Record missing evidence or explicitly state none."
  fi
  if ! markdown_section_has_content "${evidence_file}" '^[[:space:]]*##[[:space:]]+Evaluation Integrity[[:space:]]*$'; then
    add_blocker evidence_blockers_ref "missing_evaluation_integrity" "${evidence_file}#Evaluation Integrity" "Evaluation Integrity must be recorded before closing." "Record evaluation integrity notes or an explicit not-applicable note."
  fi
  if ! markdown_section_has_content "${evidence_file}" '^[[:space:]]*##[[:space:]]+Evidence Budget[[:space:]]*$'; then
    add_blocker evidence_blockers_ref "missing_evidence_budget" "${evidence_file}#Evidence Budget" "Evidence Budget must be recorded before closing." "Record the evidence budget used or remaining."
  fi
}

validate_round_evidence_discipline() {
  local round_dir="$1"
  local -n evidence_blockers_ref="$2"
  local evidence_file="${round_dir}/evidence.md"

  if [[ ! -f "${evidence_file}" ]]; then
    add_blocker evidence_blockers_ref "missing_evidence" "${evidence_file}" "Current round requires evidence.md." "Create evidence.md and record evidence discipline."
    return 0
  fi

  if ! markdown_section_has_content "${evidence_file}" '^[[:space:]]*##[[:space:]]+Missing Evidence[[:space:]]*$'; then
    add_blocker evidence_blockers_ref "missing_evidence_discipline" "${evidence_file}#Missing Evidence" "Missing Evidence must be recorded for the round." "Record missing evidence or explicitly state none."
  fi
  if ! markdown_section_has_content "${evidence_file}" '^[[:space:]]*##[[:space:]]+Evaluation Integrity[[:space:]]*$'; then
    add_blocker evidence_blockers_ref "missing_evaluation_integrity" "${evidence_file}#Evaluation Integrity" "Evaluation Integrity must be recorded for the round." "Record evaluation integrity notes or an explicit not-applicable note."
  fi
  if ! markdown_section_has_content "${evidence_file}" '^[[:space:]]*##[[:space:]]+Evidence Budget[[:space:]]*$'; then
    add_blocker evidence_blockers_ref "missing_evidence_budget" "${evidence_file}#Evidence Budget" "Evidence Budget must be recorded for the round." "Record the evidence budget used or remaining."
  fi
}

prior_continue_decision_exists() {
  local session_dir="$1"
  local current_round="$2"
  local round_number
  for ((round_number = 1; round_number < current_round; round_number++)); do
    local decision_file="${session_dir}/$(round_path "${round_number}")/decision.md"
    if [[ -f "${decision_file}" && "$(md_field_value "${decision_file}" "Decision")" == "continue" ]]; then
      return 0
    fi
  done
  return 1
}

repeated_negative_acknowledged() {
  local decision_file="$1"
  local progress_file="$2"
  local pattern='repeated negative|repeated failure|continue justified'

  if [[ -f "${decision_file}" ]] && grep -Eiq "${pattern}" "${decision_file}"; then
    return 0
  fi
  if [[ -f "${progress_file}" ]] && grep -Eiq "${pattern}" "${progress_file}"; then
    return 0
  fi
  return 1
}

validate_repeated_negative_evidence() {
  local session_dir="$1"
  local round_dir="$2"
  local current_round="$3"
  local -n repeated_blockers_ref="$4"
  local evidence_file="${round_dir}/evidence.md"
  local decision_file="${round_dir}/decision.md"
  local progress_file="${session_dir}/progress.md"

  [[ -f "${evidence_file}" ]] || return 0
  if ! markdown_section_has_content "${evidence_file}" '^[[:space:]]*##[[:space:]]+Repeated Negative Evidence[[:space:]]*$'; then
    return 0
  fi
  if ! prior_continue_decision_exists "${session_dir}" "${current_round}"; then
    return 0
  fi
  if repeated_negative_acknowledged "${decision_file}" "${progress_file}"; then
    return 0
  fi

  add_blocker repeated_blockers_ref "unacknowledged_repeated_negative_evidence" "${evidence_file}#Repeated Negative Evidence" "Repeated negative evidence after a continue decision must be acknowledged before closing." "Record why continuation or closure is justified in decision.md or progress.md, or close negative/inconclusive."
}

progress_open_questions_ready() {
  local progress_file="$1"
  local outcome="$2"
  if [[ "${outcome}" == "inconclusive" ]]; then
    return 0
  fi

  awk '
    function trim(value) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      return value
    }
    function lower(value) {
      return tolower(value)
    }
    function placeholder(value) {
      value = trim(value)
      return value == "" || value == "-" || value == "..." || lower(value) == "tbd" || lower(value) == "todo" || lower(value) == "n/a"
    }
    function separator(line) {
      return line ~ /^[[:space:]]*\|[[:space:]-]+\|[[:space:]|:-]*$/
    }
    /^## Open Questions[[:space:]]*$/ { in_section = 1; next }
    in_section && /^##[[:space:]]+/ { in_section = 0 }
    in_section && /^[[:space:]]*\|.*\|[[:space:]]*$/ {
      if (separator($0)) next
      count = split($0, parts, "|")
      question = trim(parts[2])
      blocking = lower(trim(parts[4]))
      resolution = trim(parts[5])
      if (lower(question) == "question") next
      if (!placeholder(question) && blocking ~ /^(yes|y|true|blocking)$/ && placeholder(resolution)) bad = 1
    }
    END { exit(bad ? 1 : 0) }
  ' "${progress_file}"
}

progress_deferred_items_ready() {
  local progress_file="$1"
  awk '
    function trim(value) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      return value
    }
    function lower(value) {
      return tolower(value)
    }
    function placeholder(value) {
      value = trim(value)
      return value == "" || value == "-" || value == "..." || lower(value) == "tbd" || lower(value) == "todo" || lower(value) == "n/a"
    }
    function separator(line) {
      return line ~ /^[[:space:]]*\|[[:space:]-]+\|[[:space:]|:-]*$/
    }
    /^## Deferred[[:space:]]*$/ { in_section = 1; next }
    in_section && /^##[[:space:]]+/ { in_section = 0 }
    in_section && /^[[:space:]]*\|.*\|[[:space:]]*$/ {
      if (separator($0)) next
      count = split($0, parts, "|")
      item = trim(parts[2])
      reason = trim(parts[3])
      revisit = trim(parts[4])
      if (lower(item) == "item") next
      if (!placeholder(item) && (placeholder(reason) || placeholder(revisit))) bad = 1
    }
    END { exit(bad ? 1 : 0) }
  ' "${progress_file}"
}

validate_progress_close_readiness() {
  local session_dir="$1"
  local outcome="$2"
  local -n progress_blockers_ref="$3"
  local progress_file="${session_dir}/progress.md"

  if ! progress_open_questions_ready "${progress_file}" "${outcome}"; then
    add_blocker progress_blockers_ref "unresolved_blocking_open_questions" "${progress_file}#Open Questions" "Blocking open questions must be resolved or the close must be inconclusive." "Resolve blocking open questions, mark them non-blocking, or close as inconclusive."
  fi
  if ! progress_deferred_items_ready "${progress_file}"; then
    add_blocker progress_blockers_ref "incomplete_deferred_items" "${progress_file}#Deferred" "Deferred items need a reason and revisit trigger." "Complete deferred item reason and revisit trigger before closing."
  fi
}

expected_closes_for_mode() {
  case "$1" in
    research)
      printf 'claim'
      ;;
    build)
      printf 'capability'
      ;;
    *)
      printf ''
      ;;
  esac
}

validate_round_advance_readiness() {
  local session_dir="$1"
  local mode="$2"
  local round="$3"
  local -n advance_blockers_ref="$4"

  local expected_closes
  expected_closes="$(expected_closes_for_mode "${mode}")"
  local round_dir="${session_dir}/$(round_path "${round}")"
  local review_file="${round_dir}/review.md"
  local decision_file="${round_dir}/decision.md"

  validate_review_file "${review_file}" advance_blockers_ref
  validate_decision_file "${decision_file}" "${expected_closes}" advance_blockers_ref
  validate_review_decision_alignment "${review_file}" "${decision_file}" advance_blockers_ref
  validate_mode_round_minimums "${mode}" "${round_dir}" advance_blockers_ref
  validate_round_evidence_discipline "${round_dir}" advance_blockers_ref
  validate_close_artifact_citations "${session_dir}" "${round_dir}" advance_blockers_ref
}

validate_close_readiness() {
  local session_dir="$1"
  local round_dir="$2"
  local round="$3"
  local outcome="$4"
  local -n close_blockers_ref="$5"

  validate_final_report "${session_dir}" "${outcome}" close_blockers_ref
  validate_close_evidence_discipline "${round_dir}" close_blockers_ref
  validate_progress_close_readiness "${session_dir}" "${outcome}" close_blockers_ref
  validate_close_artifact_citations "${session_dir}" "${round_dir}" close_blockers_ref
  validate_repeated_negative_evidence "${session_dir}" "${round_dir}" "${round}" close_blockers_ref
}

validate_guard_stop_readiness() {
  local session_dir="$1"
  local mode="$2"
  local round="$3"
  local -n guard_blockers_ref="$4"

  validate_round_advance_readiness "${session_dir}" "${mode}" "${round}" guard_blockers_ref

  local round_dir="${session_dir}/$(round_path "${round}")"
  local decision_file="${round_dir}/decision.md"
  local decision=""
  if [[ -f "${decision_file}" ]]; then
    decision="$(md_field_value "${decision_file}" "Decision")"
  fi

  local close_outcome=""
  case "${decision}" in
    close-positive)
      close_outcome="positive"
      ;;
    close-negative)
      close_outcome="negative"
      ;;
    close-inconclusive)
      close_outcome="inconclusive"
      ;;
  esac

  if [[ -n "${close_outcome}" ]]; then
    validate_close_readiness "${session_dir}" "${round_dir}" "${round}" "${close_outcome}" guard_blockers_ref
  fi
}

advance_to_next_round() {
  local action="$1"
  local session_dir="$2"
  local session_id="$3"
  local mode="$4"
  local round="$5"
  local -n next_result_ref="$6"
  local -n next_blockers_ref="$7"

  local expected_closes
  expected_closes="$(expected_closes_for_mode "${mode}")"
  local round_dir="${session_dir}/$(round_path "${round}")"
  local next_round=$((round + 1))
  local next_round_dir="${session_dir}/$(round_path "${next_round}")"
  if [[ -e "${next_round_dir}" ]]; then
    add_blocker next_blockers_ref "next_round_exists" "$(round_path "${next_round}")" "Next round directory already exists." "Inspect the existing next round before advancing."
    return 2
  fi

  local decision next_loop previous_decision now state_file
  state_file="${session_dir}/state.json"
  decision="$(md_field_value "${round_dir}/decision.md" "Decision")"
  next_loop="$(md_field_value "${round_dir}/decision.md" "Recommended next loop")"
  previous_decision="${decision}; closes ${expected_closes}; recommended next loop ${next_loop}"
  now="$(now_utc)"
  mkdir -p "${next_round_dir}"
  render_prompt "${mode}" "${next_round}" "Continue ${mode} session ${session_id}" "${previous_decision}" "${next_round_dir}/prompt.md"

  sed -i "s/^[[:space:]]*\"round\"[[:space:]]*:.*/  \"round\": ${next_round},/" "${state_file}"
  sed -i "s/^[[:space:]]*\"phase\"[[:space:]]*:.*/  \"phase\": \"plan\",/" "${state_file}"
  sed -i "s/^[[:space:]]*\"updated_at_utc\"[[:space:]]*:.*/  \"updated_at_utc\": \"${now}\"/" "${state_file}"

  {
    printf '\n## Round %s Decision\n\n' "${round}"
    printf '%s\n' "- Decision: ${decision}"
    printf '%s\n' "- Closes: ${expected_closes}"
    printf '%s\n' "- Recommended next loop: ${next_loop}"
    printf '%s\n' "- Next round: $(printf '%03d' "${next_round}")"
  } >> "${session_dir}/decision-ledger.md"

  next_result_ref=("${next_round}" "${next_round_dir}/prompt.md")
}

mark_session_ended() {
  local session_dir="$1"
  local status="$2"
  local now="$3"
  local state_file="${session_dir}/state.json"

  sed -i "s/^[[:space:]]*\"status\"[[:space:]]*:.*/  \"status\": \"${status}\",/" "${state_file}"
  sed -i "s/^[[:space:]]*\"phase\"[[:space:]]*:.*/  \"phase\": \"complete\",/" "${state_file}"
  sed -i "s/^[[:space:]]*\"updated_at_utc\"[[:space:]]*:.*/  \"updated_at_utc\": \"${now}\"/" "${state_file}"
}

close_session_record() {
  local session_dir="$1"
  local outcome="$2"
  local expected_closes="$3"
  local round="$4"
  local now status
  now="$(now_utc)"
  status="closed-${outcome}"
  mark_session_ended "${session_dir}" "${status}" "${now}"

  {
    printf '\n## Session Closed\n\n'
    printf '%s\n' "- Outcome: ${outcome}"
    printf '%s\n' "- Decision: close-${outcome}"
    printf '%s\n' "- Closes: ${expected_closes}"
    printf '%s\n' "- Round: $(printf '%03d' "${round}")"
    printf '%s\n' "- Closed at UTC: ${now}"
  } >> "${session_dir}/decision-ledger.md"
}

guard_transition() {
  local session_dir="$1"
  local session_id="$2"
  local mode="$3"
  local round="$4"
  local -n transition_result_ref="$5"
  local -n transition_blockers_ref="$6"

  local decision_file="${session_dir}/$(round_path "${round}")/decision.md"
  local decision expected_closes
  decision="$(md_field_value "${decision_file}" "Decision")"
  expected_closes="$(expected_closes_for_mode "${mode}")"
  case "${decision}" in
    close-positive)
      close_session_record "${session_dir}" "positive" "${expected_closes}" "${round}"
      transition_result_ref=("complete" "${round}" "closed-positive")
      ;;
    close-negative)
      close_session_record "${session_dir}" "negative" "${expected_closes}" "${round}"
      transition_result_ref=("complete" "${round}" "closed-negative")
      ;;
    close-inconclusive)
      close_session_record "${session_dir}" "inconclusive" "${expected_closes}" "${round}"
      transition_result_ref=("complete" "${round}" "closed-inconclusive")
      ;;
    *)
      local next_result=()
      if ! advance_to_next_round "guard-stop" "${session_dir}" "${session_id}" "${mode}" "${round}" next_result transition_blockers_ref; then
        return 2
      fi
      transition_result_ref=("plan" "${next_result[0]}" "${next_result[1]}")
      ;;
  esac
}

mark_guard_seen() {
  local session_dir="$1"
  local guard_session_id="$2"
  local guard_command_id="$3"
  local now="$4"
  local state_file="${session_dir}/state.json"

  if [[ -n "${guard_session_id}" ]]; then
    sed -i "s/^[[:space:]]*\"guard_session_id\"[[:space:]]*:.*/  \"guard_session_id\": \"$(json_escape "${guard_session_id}")\",/" "${state_file}"
  fi
  if [[ -n "${guard_command_id}" ]]; then
    sed -i "s/^[[:space:]]*\"last_guard_command_id\"[[:space:]]*:.*/  \"last_guard_command_id\": \"$(json_escape "${guard_command_id}")\",/" "${state_file}"
  fi
  sed -i "s/^[[:space:]]*\"updated_at_utc\"[[:space:]]*:.*/  \"updated_at_utc\": \"${now}\"/" "${state_file}"
}

cmd_guard_stop() {
  local guard_session_id=""
  local guard_command_id=""
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --guard-session-id)
        if [[ "$#" -lt 2 || -z "${2-}" || "${2-}" == --* ]]; then
          die_result "guard-stop" "missing_guard_session_id" "" "--guard-session-id requires a value." "Pass --guard-session-id <id>."
        fi
        guard_session_id="${2-}"
        shift 2
        ;;
      --guard-command-id)
        if [[ "$#" -lt 2 || -z "${2-}" || "${2-}" == --* ]]; then
          die_result "guard-stop" "missing_guard_command_id" "" "--guard-command-id requires a value." "Pass --guard-command-id <id>."
        fi
        guard_command_id="${2-}"
        shift 2
        ;;
      --json)
        shift
        ;;
      *)
        die_result "guard-stop" "unknown_option" "" "unknown option: $1" "Run rdl --help."
        ;;
    esac
  done

  local session_dir
  if ! find_session_for_audit guard-stop; then
    emit_ok "guard-stop" "" "" "" 0 "allow"
    return 0
  fi
  session_dir="${FOUND_SESSION_DIR}"

  local state_file="${session_dir}/state.json"
  local session_id mode phase round current_guard_session_id last_guard_command_id
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  phase="$(json_value "${state_file}" "phase")"
  round="$(json_number "${state_file}" "round")"
  current_guard_session_id="$(json_value "${state_file}" "guard_session_id")"
  last_guard_command_id="$(json_value "${state_file}" "last_guard_command_id")"

  if [[ -n "${guard_session_id}" && "${guard_session_id}" != "${session_id}" ]]; then
    emit_ok "guard-stop" "${session_id}" "${mode}" "${phase}" "${round:-0}" "allow"
    return 0
  fi
  if [[ -n "${guard_command_id}" && "${guard_command_id}" == "${last_guard_command_id}" ]]; then
    emit_ok "guard-stop" "${session_id}" "${mode}" "${phase}" "${round:-0}" "allow"
    return 0
  fi
  acquire_session_lock "guard-stop" "${session_dir}" "${session_id}" "${mode}" "${phase}" "${round:-0}" || return $?

  local errors=()
  local blockers=()
  validate_session "${session_dir}" errors blockers
  if [[ "${#errors[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "error" "guard-stop" "${session_id}" "${mode}" "${phase}" "${round:-0}" "block" "${errors[@]}"
    return 2
  fi
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "blocked" "guard-stop" "${session_id}" "${mode}" "${phase}" "${round:-0}" "block" "${blockers[@]}"
    return 2
  fi

  validate_guard_stop_readiness "${session_dir}" "${mode}" "${round:-1}" blockers
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "blocked" "guard-stop" "${session_id}" "${mode}" "${phase}" "${round:-0}" "block" "${blockers[@]}"
    return 2
  fi

  local session_id_needs_update=0
  local command_id_needs_update=0
  if [[ -n "${guard_session_id}" && "${guard_session_id}" != "${current_guard_session_id}" ]]; then
    session_id_needs_update=1
  fi
  if [[ -n "${guard_command_id}" && "${guard_command_id}" != "${last_guard_command_id}" ]]; then
    command_id_needs_update=1
  fi

  local transition_result=()
  guard_transition "${session_dir}" "${session_id}" "${mode}" "${round:-1}" transition_result blockers
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "blocked" "guard-stop" "${session_id}" "${mode}" "${phase}" "${round:-0}" "block" "${blockers[@]}"
    return 2
  fi

  local next_phase="${transition_result[0]}"
  local next_round="${transition_result[1]}"
  local next_action="${transition_result[2]}"
  local now
  now="$(now_utc)"
  if [[ "${session_id_needs_update}" -eq 1 || "${command_id_needs_update}" -eq 1 ]]; then
    mark_guard_seen "${session_dir}" "${guard_session_id}" "${guard_command_id}" "${now}"
  fi

  if ! refresh_integrity_or_error "guard-stop" "${session_dir}" "${session_id}" "${mode}" "${next_phase}" "${next_round:-0}"; then
    release_session_lock
    return 1
  fi
  release_session_lock
  emit_ok "guard-stop" "${session_id}" "${mode}" "${next_phase}" "${next_round:-0}" "${next_action}"
}

join_csv() {
  local first=1
  local item
  for item in "$@"; do
    if [[ "${first}" -eq 0 ]]; then
      printf ','
    fi
    first=0
    printf '%s' "${item}"
  done
}

cmd_repair() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --json)
        shift
        ;;
      *)
        die_result "repair" "unknown_option" "" "unknown option: $1" "Run rdl --help."
        ;;
    esac
  done

  local session_dir
  load_active_session repair || return $?
  session_dir="${FOUND_SESSION_DIR}"

  local state_file="${session_dir}/state.json"
  local session_id mode phase round
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  phase="$(json_value "${state_file}" "phase")"
  round="$(json_number "${state_file}" "round")"

  local repaired=()
  local errors=()
  local blockers=()
  repair_stale_session_lock "${session_dir}" repaired blockers || true
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    emit_problem "blocked" "repair" "${session_id}" "${mode}" "${phase}" "${round:-0}" "retry after lock clears" "${blockers[@]}"
    return 2
  fi
  acquire_session_lock "repair" "${session_dir}" "${session_id}" "${mode}" "${phase}" "${round:-0}" || return $?

  validate_repairable_session_structure "${session_dir}" errors blockers
  if [[ "${#errors[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "error" "repair" "${session_id}" "${mode}" "${phase}" "${round:-0}" "restore unsafe files before repair" "${errors[@]}"
    return 1
  fi
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "blocked" "repair" "${session_id}" "${mode}" "${phase}" "${round:-0}" "restore unsafe files before repair" "${blockers[@]}"
    return 2
  fi

  local manifest="${session_dir}/integrity.json"
  if ! manifest_usable_for_repair "${manifest}"; then
    validate_unverified_manifest_repair_scope "${session_dir}" errors
  else
    validate_protected_manifest_repair_scope "${session_dir}" "${manifest}" errors
  fi
  validate_existing_manifest_for_repair "${session_dir}" "${manifest}" errors blockers
  if [[ "${#errors[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "error" "repair" "${session_id}" "${mode}" "${phase}" "${round:-0}" "restore unsafe files before repair" "${errors[@]}"
    return 1
  fi
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "blocked" "repair" "${session_id}" "${mode}" "${phase}" "${round:-0}" "restore unsafe files before repair" "${blockers[@]}"
    return 2
  fi

  plan_prompt_repair "${session_dir}" repaired blockers
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "blocked" "repair" "${session_id}" "${mode}" "${phase}" "${round:-0}" "restore unsafe files before repair" "${blockers[@]}"
    return 2
  fi
  repaired+=("integrity.json")
  if ! refresh_integrity_or_error "repair" "${session_dir}" "${session_id}" "${mode}" "${phase}" "${round:-0}"; then
    release_session_lock
    return 1
  fi

  errors=()
  blockers=()
  validate_session "${session_dir}" errors blockers
  if [[ "${#errors[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "error" "repair" "${session_id}" "${mode}" "${phase}" "${round:-0}" "inspect repaired session" "${errors[@]}"
    return 1
  fi
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "blocked" "repair" "${session_id}" "${mode}" "${phase}" "${round:-0}" "inspect repaired session" "${blockers[@]}"
    return 2
  fi

  release_session_lock
  emit_ok "repair" "${session_id}" "${mode}" "${phase}" "${round:-0}" "$(join_csv "${repaired[@]}")"
}

cmd_review() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --json)
        shift
        ;;
      *)
        die_result "review" "unknown_option" "" "unknown option: $1" "Run rdl --help."
        ;;
    esac
  done

  local session_dir
  load_active_session review || return $?
  session_dir="${FOUND_SESSION_DIR}"
  validate_active_session review "${session_dir}" || return $?

  local state_file="${session_dir}/state.json"
  local session_id mode phase round
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  phase="$(json_value "${state_file}" "phase")"
  round="$(json_number "${state_file}" "round")"
  acquire_session_lock "review" "${session_dir}" "${session_id}" "${mode}" "${phase}" "${round:-0}" || return $?

  local round_dir="${session_dir}/$(round_path "${round}")"
  local review_file="${round_dir}/review.md"
  if [[ ! -f "${review_file}" ]]; then
    cp "${TEMPLATE_DIR}/review.md" "${review_file}"
    if ! refresh_integrity_or_error "review" "${session_dir}" "${session_id}" "${mode}" "${phase}" "${round}"; then
      release_session_lock
      return 1
    fi
    release_session_lock
    emit_ok "review" "${session_id}" "${mode}" "${phase}" "${round}" "${review_file}"
    return 0
  fi

  local blockers=()
  validate_review_file "${review_file}" blockers
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "blocked" "review" "${session_id}" "${mode}" "${phase}" "${round}" "complete review.md" "${blockers[@]}"
    return 2
  fi

  release_session_lock
  emit_ok "review" "${session_id}" "${mode}" "${phase}" "${round}" "rdl decide <decision-type>"
}

cmd_decide() {
  local decision_type="${1-}"
  if [[ "$#" -lt 1 ]]; then
    die_result "decide" "missing_decision_type" "" "decide requires a decision type." "rdl decide continue"
  fi
  shift
  if ! valid_decision_type "${decision_type}"; then
    die_result "decide" "invalid_decision_type" "" "unsupported decision type: ${decision_type}" "Use a planned RDL decision type."
  fi

  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --json)
        shift
        ;;
      *)
        die_result "decide" "unknown_option" "" "unknown option: $1" "Run rdl --help."
        ;;
    esac
  done

  local session_dir
  load_active_session decide || return $?
  session_dir="${FOUND_SESSION_DIR}"
  validate_active_session decide "${session_dir}" || return $?

  local state_file="${session_dir}/state.json"
  local session_id mode phase round expected_closes
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  phase="$(json_value "${state_file}" "phase")"
  round="$(json_number "${state_file}" "round")"
  acquire_session_lock "decide" "${session_dir}" "${session_id}" "${mode}" "${phase}" "${round:-0}" || return $?
  if [[ "${mode}" == "research" ]]; then
    expected_closes="claim"
  else
    expected_closes="capability"
  fi

  local round_dir="${session_dir}/$(round_path "${round}")"
  local decision_file="${round_dir}/decision.md"
  if [[ ! -f "${decision_file}" ]]; then
    cp "${TEMPLATE_DIR}/decision.md" "${decision_file}"
    sed -i "s/^Decision:.*/Decision: ${decision_type}/" "${decision_file}"
    sed -i "s/^Closes:.*/Closes: ${expected_closes}/" "${decision_file}"
    if ! refresh_integrity_or_error "decide" "${session_dir}" "${session_id}" "${mode}" "${phase}" "${round}"; then
      release_session_lock
      return 1
    fi
    release_session_lock
    emit_ok "decide" "${session_id}" "${mode}" "${phase}" "${round}" "${decision_file}"
    return 0
  fi

  local blockers=()
  validate_decision_file "${decision_file}" "${expected_closes}" blockers
  if [[ "$(md_field_value "${decision_file}" "Decision")" != "${decision_type}" ]]; then
    add_blocker blockers "decision_type_mismatch" "${decision_file}#Decision" "Decision does not match the requested decision type." "Run rdl decide with the recorded decision type or update decision.md."
  fi
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "blocked" "decide" "${session_id}" "${mode}" "${phase}" "${round}" "complete decision.md" "${blockers[@]}"
    return 2
  fi

  release_session_lock
  emit_ok "decide" "${session_id}" "${mode}" "${phase}" "${round}" "rdl next"
}

cmd_next() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --json)
        shift
        ;;
      *)
        die_result "next" "unknown_option" "" "unknown option: $1" "Run rdl --help."
        ;;
    esac
  done

  local session_dir
  load_active_session next || return $?
  session_dir="${FOUND_SESSION_DIR}"
  validate_active_session next "${session_dir}" || return $?

  local state_file="${session_dir}/state.json"
  local session_id mode phase round expected_closes
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  phase="$(json_value "${state_file}" "phase")"
  round="$(json_number "${state_file}" "round")"
  expected_closes="$(expected_closes_for_mode "${mode}")"
  acquire_session_lock "next" "${session_dir}" "${session_id}" "${mode}" "${phase}" "${round:-0}" || return $?

  local round_dir="${session_dir}/$(round_path "${round}")"
  local blockers=()
  validate_round_advance_readiness "${session_dir}" "${mode}" "${round}" blockers
  if [[ "${#blockers[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "blocked" "next" "${session_id}" "${mode}" "${phase}" "${round}" "complete current round review and decision" "${blockers[@]}"
    return 2
  fi

  local next_result=()
  if ! advance_to_next_round "next" "${session_dir}" "${session_id}" "${mode}" "${round}" next_result blockers; then
    release_session_lock
    emit_problem "blocked" "next" "${session_id}" "${mode}" "${phase}" "${round}" "inspect existing next round" "${blockers[@]}"
    return 2
  fi
  local next_round="${next_result[0]}"
  local next_prompt="${next_result[1]}"

  if ! refresh_integrity_or_error "next" "${session_dir}" "${session_id}" "${mode}" "plan" "${next_round}"; then
    release_session_lock
    return 1
  fi
  release_session_lock
  emit_ok "next" "${session_id}" "${mode}" "plan" "${next_round}" "${next_prompt}"
}

cmd_close() {
  local outcome="${1-}"
  if [[ "$#" -lt 1 ]]; then
    die_result "close" "missing_close_outcome" "" "close requires positive, negative, or inconclusive." "rdl close positive"
  fi
  shift
  if ! valid_close_outcome "${outcome}"; then
    die_result "close" "invalid_close_outcome" "" "unsupported close outcome: ${outcome}" "Use rdl close positive, negative, or inconclusive."
  fi

  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --json)
        shift
        ;;
      *)
        die_result "close" "unknown_option" "" "unknown option: $1" "Run rdl --help."
        ;;
    esac
  done

  local session_dir
  load_active_session close || return $?
  session_dir="${FOUND_SESSION_DIR}"
  validate_active_session close "${session_dir}" || return $?

  local state_file="${session_dir}/state.json"
  local session_id mode phase round expected_closes
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  phase="$(json_value "${state_file}" "phase")"
  round="$(json_number "${state_file}" "round")"
  expected_closes="$(expected_closes_for_mode "${mode}")"
  acquire_session_lock "close" "${session_dir}" "${session_id}" "${mode}" "${phase}" "${round:-0}" || return $?

  local round_dir="${session_dir}/$(round_path "${round}")"
  local decision_file="${round_dir}/decision.md"
  local expected_decision="close-${outcome}"
  local blockers=()
  validate_round_advance_readiness "${session_dir}" "${mode}" "${round}" blockers
  validate_close_readiness "${session_dir}" "${round_dir}" "${round}" "${outcome}" blockers

  if [[ -f "${decision_file}" && "$(md_field_value "${decision_file}" "Decision")" != "${expected_decision}" ]]; then
    add_blocker blockers "invalid_close_decision" "${decision_file}#Decision" "Close outcome requires Decision: ${expected_decision}." "Run rdl decide ${expected_decision} or update decision.md."
  fi

  if [[ "${#blockers[@]}" -gt 0 ]]; then
    release_session_lock
    emit_problem "blocked" "close" "${session_id}" "${mode}" "${phase}" "${round}" "complete close records" "${blockers[@]}"
    return 2
  fi

  close_session_record "${session_dir}" "${outcome}" "${expected_closes}" "${round}"

  if ! refresh_integrity_or_error "close" "${session_dir}" "${session_id}" "${mode}" "complete" "${round}"; then
    release_session_lock
    return 1
  fi
  release_session_lock
  emit_ok "close" "${session_id}" "${mode}" "complete" "${round}" "closed-${outcome}"
}

cmd_abandon() {
  if [[ "$#" -lt 1 ]]; then
    die_result "abandon" "missing_abandon_reason" "" "abandon requires a reason." "rdl abandon <reason>"
  fi

  local reason_parts=()
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --json)
        shift
        ;;
      *)
        reason_parts+=("$1")
        shift
        ;;
    esac
  done

  local reason="${reason_parts[*]}"
  reason="$(trim "${reason}")"
  if [[ -z "${reason}" ]]; then
    die_result "abandon" "missing_abandon_reason" "" "abandon requires a non-empty reason." "rdl abandon <reason>"
  fi

  local session_dir
  load_active_session abandon || return $?
  session_dir="${FOUND_SESSION_DIR}"
  validate_active_session abandon "${session_dir}" || return $?

  local state_file="${session_dir}/state.json"
  local session_id mode phase round now
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  phase="$(json_value "${state_file}" "phase")"
  round="$(json_number "${state_file}" "round")"
  acquire_session_lock "abandon" "${session_dir}" "${session_id}" "${mode}" "${phase}" "${round:-0}" || return $?
  now="$(now_utc)"

  mark_session_ended "${session_dir}" "abandoned" "${now}"

  {
    printf '\n## Session Abandoned\n\n'
    printf '%s\n' "- Reason: ${reason}"
    printf '%s\n' "- Round: $(printf '%03d' "${round}")"
    printf '%s\n' "- Abandoned at UTC: ${now}"
    printf '%s\n' "- Scientific outcome claimed: none"
  } >> "${session_dir}/decision-ledger.md"

  {
    printf '\n## Abandon Record\n\n'
    printf '%s\n' "- Reason: ${reason}"
    printf '%s\n' "- Round: $(printf '%03d' "${round}")"
    printf '%s\n' "- Scientific outcome claimed: none"
  } >> "${session_dir}/progress.md"

  if ! refresh_integrity_or_error "abandon" "${session_dir}" "${session_id}" "${mode}" "complete" "${round}"; then
    release_session_lock
    return 1
  fi
  release_session_lock
  emit_ok "abandon" "${session_id}" "${mode}" "complete" "${round}" "abandoned"
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
    review)
      cmd_review "$@"
      ;;
    decide)
      cmd_decide "$@"
      ;;
    next)
      cmd_next "$@"
      ;;
    close)
      cmd_close "$@"
      ;;
    abandon)
      cmd_abandon "$@"
      ;;
    guard-stop)
      cmd_guard_stop "$@"
      ;;
    repair)
      cmd_repair "$@"
      ;;
    *)
      die_result "unknown" "unknown_command" "" "unknown command: ${command}" "Run rdl --help."
      ;;
  esac
}

main "$@"

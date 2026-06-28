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

close_outcome_for_decision() {
  case "$1" in
    close-positive)
      printf 'positive'
      ;;
    close-negative)
      printf 'negative'
      ;;
    close-inconclusive)
      printf 'inconclusive'
      ;;
  esac
}

apply_readiness_rule() {
  local session_dir="$1"
  local mode="$2"
  local round="$3"
  local outcome="$4"
  local rule="$5"
  local -n readiness_blockers_ref="$6"
  local round_dir="${session_dir}/$(round_path "${round}")"
  local expected_closes
  expected_closes="$(expected_closes_for_mode "${mode}")"
  local review_file="${round_dir}/review.md"
  local decision_file="${round_dir}/decision.md"

  case "${rule}" in
    review)
      validate_review_file "${review_file}" readiness_blockers_ref
      ;;
    decision)
      validate_decision_file "${decision_file}" "${expected_closes}" readiness_blockers_ref
      ;;
    review-decision-alignment)
      validate_review_decision_alignment "${review_file}" "${decision_file}" readiness_blockers_ref
      ;;
    mode-minimums)
      validate_mode_round_minimums "${mode}" "${round_dir}" readiness_blockers_ref
      ;;
    round-evidence-discipline)
      validate_round_evidence_discipline "${round_dir}" readiness_blockers_ref
      ;;
    artifact-citations)
      validate_close_artifact_citations "${session_dir}" "${round_dir}" readiness_blockers_ref
      ;;
    final-report)
      validate_final_report "${session_dir}" "${outcome}" readiness_blockers_ref
      ;;
    close-evidence-discipline)
      validate_close_evidence_discipline "${round_dir}" readiness_blockers_ref
      ;;
    progress-close-readiness)
      validate_progress_close_readiness "${session_dir}" "${outcome}" readiness_blockers_ref
      ;;
    repeated-negative-evidence)
      validate_repeated_negative_evidence "${session_dir}" "${round_dir}" "${round}" readiness_blockers_ref
      ;;
    close-if-decision)
      if [[ -f "${decision_file}" ]]; then
        local decision close_outcome
        decision="$(md_field_value "${decision_file}" "Decision")"
        close_outcome="$(close_outcome_for_decision "${decision}")"
        if [[ -n "${close_outcome}" ]]; then
          apply_readiness_plan "close" "${session_dir}" "${mode}" "${round}" "${close_outcome}" readiness_blockers_ref
        fi
      fi
      ;;
    *)
      add_blocker readiness_blockers_ref "invalid_readiness_rule" "${rule}" "Internal readiness rule is unsupported." "Fix the RDL readiness descriptor."
      ;;
  esac
}

apply_readiness_plan() {
  local plan="$1"
  local session_dir="$2"
  local mode="$3"
  local round="$4"
  local outcome="$5"
  local -n plan_blockers_ref="$6"
  local rule
  while IFS= read -r rule; do
    [[ -n "${rule}" ]] || continue
    apply_readiness_rule "${session_dir}" "${mode}" "${round}" "${outcome}" "${rule}" plan_blockers_ref
  done < <(descriptor_readiness_rules "${plan}")
}

validate_current_round_record() {
  local session_dir="$1"
  local mode="$2"
  local round="$3"
  local -n round_blockers_ref="$4"

  apply_readiness_plan "doctor-current" "${session_dir}" "${mode}" "${round}" "" round_blockers_ref
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
  descriptor_value_allowed "$1" decision-type
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
  if ! descriptor_value_allowed "${value}" review-mode; then
    add_blocker blockers_ref "invalid_review_mode" "${file}#Review Mode" "Review Mode is unsupported." "Use manual, checklist, phase-review, subagent, or project-adapter."
  fi

  value="$(md_field_value "${file}" "Verdict")"
  if ! descriptor_value_allowed "${value}" review-verdict; then
    add_blocker blockers_ref "invalid_review_verdict" "${file}#Verdict" "Verdict is unsupported." "Use PASS, PASS_WITH_NOTES, BLOCKED, or INCONCLUSIVE."
  fi
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
  if ! descriptor_value_allowed "${next_loop}" recommended-next-loop; then
    add_blocker blockers_ref "invalid_recommended_next_loop" "${file}#Recommended next loop" "Recommended next loop is unsupported." "Use research, build, or none."
  fi
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
  descriptor_value_allowed "$1" close-outcome
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
  descriptor_expected_closes_for_mode "$1"
}

validate_round_advance_readiness() {
  local session_dir="$1"
  local mode="$2"
  local round="$3"
  local -n advance_blockers_ref="$4"

  apply_readiness_plan "advance" "${session_dir}" "${mode}" "${round}" "" advance_blockers_ref
}

validate_close_readiness() {
  local session_dir="$1"
  local round_dir="$2"
  local round="$3"
  local outcome="$4"
  local -n close_blockers_ref="$5"
  local mode

  mode="$(json_value "${session_dir}/state.json" "mode")"
  apply_readiness_plan "close" "${session_dir}" "${mode}" "${round}" "${outcome}" close_blockers_ref
}

validate_guard_stop_readiness() {
  local session_dir="$1"
  local mode="$2"
  local round="$3"
  local -n guard_blockers_ref="$4"

  apply_readiness_plan "guard-stop-advance" "${session_dir}" "${mode}" "${round}" "" guard_blockers_ref

  local round_dir="${session_dir}/$(round_path "${round}")"
  local decision_file="${round_dir}/decision.md"
  local decision=""
  if [[ -f "${decision_file}" ]]; then
    decision="$(md_field_value "${decision_file}" "Decision")"
  fi

  local close_outcome=""
  close_outcome="$(close_outcome_for_decision "${decision}")"

  if [[ -n "${close_outcome}" ]]; then
    apply_readiness_plan "guard-stop-close" "${session_dir}" "${mode}" "${round}" "${close_outcome}" guard_blockers_ref
  fi
}

transition_update_state_field() {
  local state_file="$1"
  local field="$2"
  local value="$3"
  local comma=","
  if [[ "$#" -ge 4 ]]; then
    comma="$4"
  fi

  sed -i "s/^[[:space:]]*\"${field}\"[[:space:]]*:.*/  \"${field}\": ${value}${comma}/" "${state_file}"
}

transition_update_state_string() {
  local state_file="$1"
  local field="$2"
  local value="$3"
  local comma=","
  if [[ "$#" -ge 4 ]]; then
    comma="$4"
  fi

  transition_update_state_field "${state_file}" "${field}" "\"$(json_escape "${value}")\"" "${comma}"
}

transition_mark_session_ended() {
  local session_dir="$1"
  local status="$2"
  local now="$3"
  local state_file="${session_dir}/state.json"

  transition_update_state_string "${state_file}" "status" "${status}"
  transition_update_state_string "${state_file}" "phase" "complete"
  transition_update_state_string "${state_file}" "updated_at_utc" "${now}" ""
}

transition_append_round_decision() {
  local session_dir="$1"
  local round="$2"
  local decision="$3"
  local expected_closes="$4"
  local next_loop="$5"
  local next_round="$6"

  {
    printf '\n## Round %s Decision\n\n' "${round}"
    printf '%s\n' "- Decision: ${decision}"
    printf '%s\n' "- Closes: ${expected_closes}"
    printf '%s\n' "- Recommended next loop: ${next_loop}"
    printf '%s\n' "- Next round: $(printf '%03d' "${next_round}")"
  } >> "${session_dir}/decision-ledger.md"
}

transition_append_close_record() {
  local session_dir="$1"
  local outcome="$2"
  local expected_closes="$3"
  local round="$4"
  local now="$5"

  {
    printf '\n## Session Closed\n\n'
    printf '%s\n' "- Outcome: ${outcome}"
    printf '%s\n' "- Decision: close-${outcome}"
    printf '%s\n' "- Closes: ${expected_closes}"
    printf '%s\n' "- Round: $(printf '%03d' "${round}")"
    printf '%s\n' "- Closed at UTC: ${now}"
  } >> "${session_dir}/decision-ledger.md"
}

transition_append_abandon_records() {
  local session_dir="$1"
  local reason="$2"
  local round="$3"
  local now="$4"

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
}

transition_advance_to_next_round() {
  local session_dir="$1"
  local session_id="$2"
  local mode="$3"
  local round="$4"
  local -n next_result_ref="$5"
  local -n next_blockers_ref="$6"

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

  transition_update_state_field "${state_file}" "round" "${next_round}"
  transition_update_state_string "${state_file}" "phase" "plan"
  transition_update_state_string "${state_file}" "updated_at_utc" "${now}" ""
  transition_append_round_decision "${session_dir}" "${round}" "${decision}" "${expected_closes}" "${next_loop}" "${next_round}"

  next_result_ref=("${next_round}" "${next_round_dir}/prompt.md")
}

advance_to_next_round() {
  shift
  transition_advance_to_next_round "$@"
}

mark_session_ended() {
  local session_dir="$1"
  local status="$2"
  local now="$3"

  transition_mark_session_ended "${session_dir}" "${status}" "${now}"
}

transition_close_session() {
  local session_dir="$1"
  local outcome="$2"
  local expected_closes="$3"
  local round="$4"
  local now status
  now="$(now_utc)"
  status="closed-${outcome}"
  transition_mark_session_ended "${session_dir}" "${status}" "${now}"
  transition_append_close_record "${session_dir}" "${outcome}" "${expected_closes}" "${round}" "${now}"
}

close_session_record() {
  transition_close_session "$@"
}

transition_abandon_session() {
  local session_dir="$1"
  local reason="$2"
  local round="$3"
  local now
  now="$(now_utc)"

  transition_mark_session_ended "${session_dir}" "abandoned" "${now}"
  transition_append_abandon_records "${session_dir}" "${reason}" "${round}" "${now}"
}

transition_from_decision() {
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
      transition_close_session "${session_dir}" "positive" "${expected_closes}" "${round}"
      transition_result_ref=("complete" "${round}" "closed-positive")
      ;;
    close-negative)
      transition_close_session "${session_dir}" "negative" "${expected_closes}" "${round}"
      transition_result_ref=("complete" "${round}" "closed-negative")
      ;;
    close-inconclusive)
      transition_close_session "${session_dir}" "inconclusive" "${expected_closes}" "${round}"
      transition_result_ref=("complete" "${round}" "closed-inconclusive")
      ;;
    *)
      local next_result=()
      if ! transition_advance_to_next_round "${session_dir}" "${session_id}" "${mode}" "${round}" next_result transition_blockers_ref; then
        return 2
      fi
      transition_result_ref=("plan" "${next_result[0]}" "${next_result[1]}")
      ;;
  esac
}

guard_transition() {
  transition_from_decision "$@"
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
  local session_id mode phase round
  session_id="$(json_value "${state_file}" "session_id")"
  mode="$(json_value "${state_file}" "mode")"
  phase="$(json_value "${state_file}" "phase")"
  round="$(json_number "${state_file}" "round")"
  acquire_session_lock "abandon" "${session_dir}" "${session_id}" "${mode}" "${phase}" "${round:-0}" || return $?
  transition_abandon_session "${session_dir}" "${reason}" "${round}"

  if ! refresh_integrity_or_error "abandon" "${session_dir}" "${session_id}" "${mode}" "complete" "${round}"; then
    release_session_lock
    return 1
  fi
  release_session_lock
  emit_ok "abandon" "${session_id}" "${mode}" "complete" "${round}" "abandoned"
}

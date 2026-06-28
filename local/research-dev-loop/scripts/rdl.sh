#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE_DIR="${SKILL_DIR}/templates"

RDL_DIR=".rdl"
SESSIONS_DIR="${RDL_DIR}/sessions"
FOUND_SESSION_DIR=""

source "${SCRIPT_DIR}/lib/rdl_core.sh"
source "${SCRIPT_DIR}/lib/rdl_commands.sh"

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

if [[ "${RDL_LIB_ONLY:-0}" != "1" ]]; then
  main "$@"
fi

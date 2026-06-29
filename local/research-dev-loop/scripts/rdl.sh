#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${RDL_PYTHON_BIN:-python3}"

if [[ -n "${PYTHONPATH:-}" ]]; then
  export PYTHONPATH="${SKILL_DIR}:${PYTHONPATH}"
else
  export PYTHONPATH="${SKILL_DIR}"
fi

case "${1:-}" in
  ""|-h|--help)
    exec "${PYTHON_BIN}" -m rdl "$@"
    ;;
esac

for arg in "$@"; do
  if [[ "${arg}" == "--json" ]]; then
    exec "${PYTHON_BIN}" -m rdl "$@"
  fi
done

exec "${PYTHON_BIN}" -m rdl "$@" --json

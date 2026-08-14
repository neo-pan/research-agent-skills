#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RDL_AUDIT_USAGE="scripts/rdl_dogfood_audit.sh" \
  exec "${ROOT_DIR}/local/research-dev-loop/bin/rdl-audit" "$@"

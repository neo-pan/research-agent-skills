#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${ROOT_DIR}/local/research-dev-loop/SKILL.md"
ORCHESTRATOR="${ROOT_DIR}/local/rdl-orchestrator/SKILL.md"
SEMANTIC="${ROOT_DIR}/local/research-dev-loop/SEMANTIC_REVIEW.md"
CLI_REFERENCE="${ROOT_DIR}/local/research-dev-loop/CLI.md"

body_bytes() {
  awk 'BEGIN { markers=0; body=0 } /^---$/ { markers++; if (markers == 2) { body=1; next } } body { print }' "$1" | wc -c
}

base_body="$(body_bytes "${BASE}")"
orchestrator_body="$(body_bytes "${ORCHESTRATOR}")"
semantic_bytes="$(wc -c <"${SEMANTIC}")"
routine_bytes="$(( $(wc -c <"${BASE}") + $(wc -c <"${ORCHESTRATOR}") + $(wc -c <"${CLI_REFERENCE}") ))"

[[ "${base_body}" -le 2867 ]] || { echo "research-dev-loop body exceeds 2.8 KiB" >&2; exit 1; }
[[ "${orchestrator_body}" -le 2048 ]] || { echo "rdl-orchestrator body exceeds 2 KiB" >&2; exit 1; }
[[ "${semantic_bytes}" -le 2048 ]] || { echo "semantic reference exceeds 2 KiB" >&2; exit 1; }
[[ "${routine_bytes}" -le 6144 ]] || { echo "routine RDL load exceeds 6 KiB" >&2; exit 1; }

echo "RDL skill budgets ok"

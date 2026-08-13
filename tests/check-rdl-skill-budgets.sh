#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${ROOT_DIR}/local/research-dev-loop/SKILL.md"
ORCHESTRATOR="${ROOT_DIR}/local/rdl-orchestrator/SKILL.md"
SEMANTIC="${ROOT_DIR}/local/research-dev-loop/SEMANTIC_REVIEW.md"
PREPARATION="${ROOT_DIR}/local/research-dev-loop/PRE_REVIEW_PREPARATION.md"
CLI_REFERENCE="${ROOT_DIR}/local/research-dev-loop/CLI.md"

body_bytes() {
  awk 'BEGIN { markers=0; body=0 } /^---$/ { markers++; if (markers == 2) { body=1; next } } body { print }' "$1" | wc -c
}

base_body="$(body_bytes "${BASE}")"
orchestrator_body="$(body_bytes "${ORCHESTRATOR}")"
semantic_bytes="$(wc -c <"${SEMANTIC}")"
preparation_bytes="$(wc -c <"${PREPARATION}")"
routine_bytes="$(( $(wc -c <"${BASE}") + $(wc -c <"${ORCHESTRATOR}") + $(wc -c <"${CLI_REFERENCE}") ))"
material_reference_bytes="$(( semantic_bytes + preparation_bytes ))"

grep -Fq 'Do not precompute file sizes or checksums for artifact entries' "${BASE}" \
  || { echo "research-dev-loop must delegate artifact integrity metadata to apply" >&2; exit 1; }
grep -Fq 'checksum-only commands such as `sha256sum` are redundant' "${BASE}" \
  || { echo "research-dev-loop must reject redundant checksum-only verification" >&2; exit 1; }
grep -Fq 'routine applies stay in-round' "${BASE}" \
  || { echo "research-dev-loop must keep routine checkpoints reviewer-free" >&2; exit 1; }
grep -Fq 'start one only when explicitly requested' "${BASE}" \
  || { echo "research-dev-loop must require explicit authorization for new sessions" >&2; exit 1; }
grep -Fq 'obtain its PASS before `start`' "${BASE}" \
  || { echo "research-dev-loop must review gated missions before start" >&2; exit 1; }
grep -Fq 'resolve each `active` progress item' "${BASE}" \
  || { echo "research-dev-loop must reconcile active progress before terminal close" >&2; exit 1; }
grep -Fq 'Do not run semantic review, `apply`, `next`, or `close` unless the user asks' "${BASE}" \
  || { echo "research-dev-loop inspection must remain read-only" >&2; exit 1; }
grep -Fq "project-review reference" "${ORCHESTRATOR}" \
  || { echo "rdl-orchestrator must preserve the material-build review gate" >&2; exit 1; }

[[ "${base_body}" -le 2867 ]] || { echo "research-dev-loop body exceeds 2.8 KiB" >&2; exit 1; }
[[ "${orchestrator_body}" -le 2048 ]] || { echo "rdl-orchestrator body exceeds 2 KiB" >&2; exit 1; }
[[ "${semantic_bytes}" -le 2048 ]] || { echo "semantic reference exceeds 2 KiB" >&2; exit 1; }
[[ "${preparation_bytes}" -le 2048 ]] || { echo "pre-review preparation reference exceeds 2 KiB" >&2; exit 1; }
[[ "${material_reference_bytes}" -le 4096 ]] || { echo "material review references exceed 4 KiB" >&2; exit 1; }
[[ "${routine_bytes}" -le 6144 ]] || { echo "routine RDL load exceeds 6 KiB" >&2; exit 1; }

echo "RDL skill budgets ok"

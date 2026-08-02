#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${ROOT_DIR}/codex/agents"
INSTALLER="${ROOT_DIR}/scripts/install_recommended_codex_agents.sh"
ORCHESTRATOR="${ROOT_DIR}/local/rdl-orchestrator/CODEX.md"
SEMANTIC_REVIEW="${ROOT_DIR}/local/research-dev-loop/SEMANTIC_REVIEW.md"
PHASE_REVIEW="${ROOT_DIR}/local/phase-review/SKILL.md"
PHASE_REVIEW_AGENT="${ROOT_DIR}/local/phase-review/agents/openai.yaml"
RDL_SKILL_AGENT="${ROOT_DIR}/local/research-dev-loop/agents/openai.yaml"
RDL_ORCHESTRATOR_SKILL="${ROOT_DIR}/local/rdl-orchestrator/SKILL.md"
RDL_ORCHESTRATOR_AGENT="${ROOT_DIR}/local/rdl-orchestrator/agents/openai.yaml"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_setting() {
  local file="$1"
  local setting="$2"
  grep -Fxq "${setting}" "${file}" \
    || fail "$(basename "${file}") missing expected setting: ${setting}"
}

assert_contains() {
  local file="$1"
  local text="$2"
  grep -Fqi "${text}" "${file}" \
    || fail "${file#"${ROOT_DIR}/"} missing expected contract text: ${text}"
}

reviewer="${SOURCE_DIR}/rdl-reviewer.toml"
explorer="${SOURCE_DIR}/rdl-explorer.toml"

for config in "${reviewer}" "${explorer}"; do
  [[ -f "${config}" ]] || fail "missing agent config: ${config}"
  grep -q '^name = ' "${config}" || fail "$(basename "${config}") missing name"
  grep -q '^description = ' "${config}" || fail "$(basename "${config}") missing description"
  grep -q '^developer_instructions = ' "${config}" \
    || fail "$(basename "${config}") missing developer_instructions"
done

assert_setting "${reviewer}" 'model = "gpt-5.6-sol"'
assert_setting "${reviewer}" 'model_reasoning_effort = "high"'
assert_setting "${reviewer}" 'sandbox_mode = "read-only"'
assert_setting "${explorer}" 'model = "gpt-5.6-terra"'
assert_setting "${explorer}" 'model_reasoning_effort = "medium"'
assert_setting "${explorer}" 'sandbox_mode = "read-only"'

for config in "${reviewer}" "${explorer}"; do
  assert_contains "${config}" "Do not rely on parent conversation history"
  assert_contains "${config}" "do not return a transcript"
done

assert_contains "${reviewer}" "action, subject_digest, adapter, verdict, and concise typed findings"
assert_contains "${reviewer}" "Do not use tools or inspect files"
assert_contains "${reviewer}" "digest-bound receipt or excerpt"
if grep -Fqi 'verification artifacts' "${reviewer}" "${ORCHESTRATOR}"; then
  fail "semantic reviewer inputs must be pack-only"
fi
assert_contains "${explorer}" "contradictions"
assert_contains "${ORCHESTRATOR}" 'fork_turns="none"'
assert_contains "${ORCHESTRATOR}" "main transcript"
assert_contains "${ORCHESTRATOR}" "use at most one"
assert_contains "${SEMANTIC_REVIEW}" 'fork_turns="none"'
assert_contains "${PHASE_REVIEW}" 'fork_turns="none"'
assert_setting "${RDL_SKILL_AGENT}" '  display_name: "Research Development Loop"'
assert_setting "${RDL_SKILL_AGENT}" '  short_description: "Run durable evidence-backed research and build sessions"'
assert_contains "${RDL_SKILL_AGENT}" '$research-dev-loop'
assert_setting "${PHASE_REVIEW_AGENT}" '  allow_implicit_invocation: false'
assert_setting "${RDL_ORCHESTRATOR_AGENT}" '  allow_implicit_invocation: false'
if grep -Fq 'allow_implicit_invocation: false' "${RDL_SKILL_AGENT}"; then
  fail "research-dev-loop must remain available for implicit invocation"
fi
if grep -Fq 'disable-model-invocation' "${PHASE_REVIEW}" "${RDL_ORCHESTRATOR_SKILL}"; then
  fail "manual skill invocation policy must live in agents/openai.yaml"
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

"${INSTALLER}" "${tmp_dir}/agents" >/dev/null
"${INSTALLER}" "${tmp_dir}/agents" >/dev/null

for config in "${reviewer}" "${explorer}"; do
  installed="${tmp_dir}/agents/$(basename "${config}")"
  [[ -L "${installed}" ]] || fail "installer did not create symlink: ${installed}"
  [[ "$(readlink -f "${installed}")" == "$(realpath "${config}")" ]] \
    || fail "installed symlink has wrong target: ${installed}"
done

rm "${tmp_dir}/agents/rdl-reviewer.toml"
printf 'user-owned\n' >"${tmp_dir}/agents/rdl-reviewer.toml"
if "${INSTALLER}" "${tmp_dir}/agents" >"${tmp_dir}/stdout" 2>"${tmp_dir}/stderr"; then
  fail "installer should refuse to replace a non-symlink config"
fi
grep -q 'kind=file' "${tmp_dir}/stderr" \
  || fail "installer file-conflict details are missing"
grep -Fxq 'user-owned' "${tmp_dir}/agents/rdl-reviewer.toml" \
  || fail "installer changed the conflicting user-owned file"

echo "Recommended Codex agent configs ok"

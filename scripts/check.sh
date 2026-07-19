#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "${ROOT_DIR}/scripts/lib/selected_skills.sh"

usage() {
  cat <<'EOF'
Usage: scripts/check.sh

Run manifest/link checks, RDL Python tests, and prerequisites.
EOF
}

case "${1:-}" in
  "")
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [[ "$#" -gt 1 ]]; then
  usage >&2
  exit 2
fi

selected_skills_load "${ROOT_DIR}"
selected_skills_validate_manifest

total_count="$(selected_skills_count)"
echo "Manifest ok: ${total_count} skills"

"${ROOT_DIR}/scripts/link_selected_skills.sh" >/dev/null

broken_links=0
while IFS= read -r -d '' link_path; do
  if [[ ! -e "${link_path}" ]]; then
    echo "Broken skill link: ${link_path}" >&2
    broken_links=1
  fi
done < <(find "${ROOT_DIR}/skills" -maxdepth 1 -type l -print0)

if [[ "${broken_links}" -ne 0 ]]; then
  exit 1
fi

echo "Skill links ok"

bash "${ROOT_DIR}/tests/check-selected-skills-module.sh" >/dev/null

echo "Selected skills module ok"

bash "${ROOT_DIR}/tests/check-installed-skills-module.sh" >/dev/null

echo "Installed skills module ok"

bash "${ROOT_DIR}/tests/check-upstream-install-guard.sh" >/dev/null

echo "Upstream install guard ok"

bash "${ROOT_DIR}/tests/check-recommended-codex-agents.sh" >/dev/null

echo "Recommended Codex agent configs ok"

bash "${ROOT_DIR}/tests/check-rdl-skill-budgets.sh" >/dev/null

echo "RDL skill budgets ok"

RDL_LAUNCHER="${ROOT_DIR}/local/research-dev-loop/bin/rdl"
[[ -x "${RDL_LAUNCHER}" ]] || { echo "RDL launcher is not executable: ${RDL_LAUNCHER}" >&2; exit 1; }

if ! command -v python3 >/dev/null 2>&1; then
  echo "Missing python3: RDL Python tests require python3 for repository checks." >&2
  exit 1
fi

PYTHONPATH="${ROOT_DIR}/local/research-dev-loop" \
  python3 -m unittest discover -s "${ROOT_DIR}/local/research-dev-loop/tests_py" >/dev/null

echo "RDL Python tests ok"

"${ROOT_DIR}/tests/check-rdl-command-installer.py" >/dev/null

echo "RDL command installer ok"

bash "${ROOT_DIR}/tests/check-removed-check-modes.sh" >/dev/null

echo "Removed check modes ok"

bash "${ROOT_DIR}/tests/check-rdl-dogfood-audit.sh" >/dev/null

echo "RDL dogfood audit ok"

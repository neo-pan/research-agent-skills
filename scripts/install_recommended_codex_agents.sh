#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="${ROOT_DIR}/codex/agents"
TARGET_DIR="${1:-${CODEX_HOME:-${HOME}/.codex}/agents}"

mkdir -p "${TARGET_DIR}"

installed=0
for source_path in "${SOURCE_DIR}"/*.toml; do
  agent_name="$(basename "${source_path}")"
  target_path="${TARGET_DIR}/${agent_name}"

  if [[ -e "${target_path}" && ! -L "${target_path}" ]]; then
    echo "Refusing to replace non-symlink agent config: ${target_path}" >&2
    exit 1
  fi

  ln -sfn "$(realpath "${source_path}")" "${target_path}"
  installed=$((installed + 1))
done

echo "Installed ${installed} recommended Codex agent configs into ${TARGET_DIR}"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "${ROOT_DIR}/scripts/lib/selected_skills.sh"

selected_skills_load "${ROOT_DIR}"
UPSTREAM_DIR="$(selected_skills_upstream_dir)"

git -C "${ROOT_DIR}" submodule update --init --recursive
selected_skills_validate_manifest
git -C "${UPSTREAM_DIR}" fetch origin
git -C "${UPSTREAM_DIR}" checkout main
git -C "${UPSTREAM_DIR}" pull --ff-only origin main

"${ROOT_DIR}/scripts/link_selected_skills.sh"

echo
echo "Upstream commit:"
git -C "${UPSTREAM_DIR}" rev-parse HEAD
echo
echo "Review and commit the submodule update from ${ROOT_DIR}."

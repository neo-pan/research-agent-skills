#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_DIR="${ROOT_DIR}/upstream/mattpocock-skills"

git -C "${ROOT_DIR}" submodule update --init --recursive
git -C "${UPSTREAM_DIR}" fetch origin
git -C "${UPSTREAM_DIR}" checkout main
git -C "${UPSTREAM_DIR}" pull --ff-only origin main

"${ROOT_DIR}/scripts/link_selected_skills.sh"

echo
echo "Upstream commit:"
git -C "${UPSTREAM_DIR}" rev-parse HEAD
echo
echo "Review and commit the submodule update from ${ROOT_DIR}."


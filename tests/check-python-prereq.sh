#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

if "${ROOT_DIR}/scripts/check.sh" --fast >"${tmp_dir}/stdout" 2>"${tmp_dir}/stderr"; then
  fail "check unexpectedly accepted removed --fast mode"
fi

grep -q "Usage: scripts/check.sh" "${tmp_dir}/stderr" \
  || fail "removed-mode usage message was not emitted"

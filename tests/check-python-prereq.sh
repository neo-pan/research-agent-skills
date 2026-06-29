#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

if RDL_PYTHON_BIN=rdl-python3-missing "${ROOT_DIR}/scripts/check.sh" --fast >"${tmp_dir}/stdout" 2>"${tmp_dir}/stderr"; then
  fail "short check unexpectedly succeeded without python3"
fi

grep -q "Missing python3: RDL Python tests require python3 for repository checks." "${tmp_dir}/stderr" \
  || fail "missing-python prerequisite message was not emitted"

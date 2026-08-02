#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDIT="${ROOT_DIR}/scripts/rdl_dogfood_audit.sh"
RDL="${ROOT_DIR}/local/research-dev-loop/bin/rdl"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

create_session() {
  local project_root="$1"
  local session_id="$2"
  PYTHONPATH="${ROOT_DIR}/local/research-dev-loop" python3 - "${project_root}" "${session_id}" <<'PY'
import sys
from pathlib import Path
from rdl import RdlEngine

root = Path(sys.argv[1])
RdlEngine(root).execute(
    "start",
    session_id=sys.argv[2],
    request={
        "mode": "research",
        "mission": {
            "objective": "dogfood fixture",
            "scope": ["fixture"],
            "out_of_scope": [],
            "success_criteria": ["state is recoverable"],
            "invariants": [],
            "abort_criteria": [],
        },
    },
)
PY
}

healthy="${tmp_dir}/healthy"
mkdir -p "${healthy}"
create_session "${healthy}" audit
"${AUDIT}" --subagent-calls 0 --json-output "${tmp_dir}/healthy.json" "${healthy}" >"${tmp_dir}/healthy.out"
(cd "${healthy}" && "${RDL}" doctor --diagnostics --session-id audit) >"${tmp_dir}/healthy-doctor.json"
grep -q "Audit: PASS" "${tmp_dir}/healthy.out" || fail "healthy session should pass"
grep -q "session: audit" "${tmp_dir}/healthy.out" || fail "audit should show selected session"
python3 - "${tmp_dir}/healthy.json" "${tmp_dir}/healthy-doctor.json" <<'PY'
import json
import sys
from pathlib import Path

receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
doctor = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert receipt["status"] == "pass"
assert receipt["session_status"] == "active"
assert [item["name"] for item in receipt["probes"]] == ["handoff", "doctor"]
assert receipt["accounting"] == {
    "projections": doctor["diagnostics"]["projections"],
    "reported_subagent_calls": 0,
}
assert receipt["before"] == receipt["after"]
assert all(receipt["unchanged"].values())
PY

if "${AUDIT}" "${healthy}" >"${tmp_dir}/missing-count.out" 2>"${tmp_dir}/missing-count.err"; then
  fail "audit should require caller-reported subagent count"
fi
grep -q -- "--subagent-calls is required" "${tmp_dir}/missing-count.err" || fail "missing count error absent"

if "${AUDIT}" --subagent-calls -1 "${healthy}" >"${tmp_dir}/negative-count.out" 2>"${tmp_dir}/negative-count.err"; then
  fail "audit should reject a negative subagent count"
fi
grep -q "non-negative integer" "${tmp_dir}/negative-count.err" || fail "negative count error absent"

if "${AUDIT}" --subagent-calls many "${healthy}" >"${tmp_dir}/invalid-count.out" 2>"${tmp_dir}/invalid-count.err"; then
  fail "audit should reject a non-integer subagent count"
fi
grep -q "non-negative integer" "${tmp_dir}/invalid-count.err" || fail "invalid count error absent"

terminal="${tmp_dir}/terminal"
mkdir -p "${terminal}"
PYTHONPATH="${ROOT_DIR}/local/research-dev-loop" python3 - "${terminal}" <<'PY'
import json
import sys
from pathlib import Path
from rdl import RdlEngine

root = Path(sys.argv[1])
engine = RdlEngine(root)
mission = {
    "objective": "audit every terminal outcome",
    "scope": ["terminal audit fixture"],
    "out_of_scope": [],
    "success_criteria": ["terminal state is recoverable"],
    "invariants": [],
    "abort_criteria": [],
}
for outcome in ("positive", "negative", "inconclusive", "abandoned"):
    session_id = f"terminal-{outcome}"
    engine.execute("start", session_id=session_id, request={"mode": "research", "mission": mission})
    if outcome == "abandoned":
        engine.execute(
            "close", session_id=session_id, expected_state_version=1,
            outcome=outcome, reason="fixture complete",
        )
        continue

    artifact = root / f"{outcome}.json"
    artifact.write_text(json.dumps({"outcome": outcome}) + "\n", encoding="utf-8")
    applied = engine.execute(
        "apply",
        session_id=session_id,
        request={
            "expected_state_version": 1,
            "risk": "material",
            "artifacts": {
                "receipt": {
                    "kind": "receipt",
                    "path": artifact.name,
                    "description": f"{outcome} fixture receipt",
                    "stability": "snapshot",
                }
            },
            "evidence": {
                "result": {
                    "claim": f"the fixture supports {outcome}",
                    "summary": "the bounded fixture completed",
                    "bearing": "supports",
                    "strength": "strong",
                    "artifact_refs": ["receipt"],
                    "uncertainty": "fixture-scoped",
                }
            },
            "decision": {
                "kind": "accept",
                "subject": f"close the bounded fixture as {outcome}",
                "evidence_refs": ["result"],
                "uncertainty": "fixture-scoped",
                "remaining_unknowns": [],
                "next_step": "close the bounded fixture",
                "recommended_transition": "close",
                "close_outcome": outcome,
            },
        },
    )
    engine.execute(
        "apply",
        session_id=session_id,
        request={
            "expected_state_version": 2,
            "risk": "routine",
            "review_result": {
                "action": "close",
                "subject_digest": applied["review_subject_digest"],
                "adapter": "fixture-reviewer",
                "verdict": "pass",
                "findings": [],
            },
        },
    )
    engine.execute(
        "close", session_id=session_id, expected_state_version=3, outcome=outcome,
    )
PY

for outcome in positive negative inconclusive abandoned; do
  session_id="terminal-${outcome}"
  "${AUDIT}" --session-id "${session_id}" --subagent-calls 1 --json-output "${tmp_dir}/${session_id}.json" "${terminal}" >"${tmp_dir}/${session_id}.out"
  (cd "${terminal}" && "${RDL}" doctor --diagnostics --session-id "${session_id}") >"${tmp_dir}/${session_id}-doctor.json"
  grep -q "Audit: PASS" "${tmp_dir}/${session_id}.out" || fail "${outcome} terminal session should pass"
  python3 - "${tmp_dir}/${session_id}.json" "${outcome}" "${tmp_dir}/${session_id}-doctor.json" <<'PY'
import json
import sys
from pathlib import Path

receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
outcome = sys.argv[2]
doctor = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
assert receipt["status"] == "pass"
assert receipt["session_id"] == f"terminal-{outcome}"
assert receipt["session_status"] == (outcome if outcome == "abandoned" else f"closed-{outcome}")
assert receipt["accounting"] == {
    "projections": doctor["diagnostics"]["projections"],
    "reported_subagent_calls": 1,
}
probes = {item["name"]: item for item in receipt["probes"]}
assert set(probes) == {
    "handoff", "doctor", "exact_close_replay", "terminal_apply",
    "terminal_next", "terminal_close", "stale_apply",
}
assert probes["exact_close_replay"]["exit_code"] == 0
assert probes["exact_close_replay"]["typed_result"]["matches_stored_receipt"] is True
for name in ("terminal_apply", "terminal_next", "terminal_close"):
    assert probes[name]["exit_code"] == 2
    assert probes[name]["typed_result"]["code"] == "terminal_session"
assert probes["stale_apply"]["typed_result"]["code"] == "state_version_conflict"
assert all(receipt["unchanged"].values())
assert receipt["before"] == receipt["after"]
assert receipt["before"]["store_digest"]["algorithm"] == "sha256-tree-v1:path-type-content"
assert receipt["before"]["store_digest"]["exclusions"] == []
PY
done

if "${AUDIT}" --session-id terminal-abandoned --subagent-calls 0 --json-output "${terminal}/.rdl/audit.json" "${terminal}" >"${tmp_dir}/unsafe.out" 2>"${tmp_dir}/unsafe.err"; then
  fail "audit receipt must not be written inside .rdl"
fi
grep -q "must not write inside .rdl" "${tmp_dir}/unsafe.err" || fail "unsafe output error missing"

empty="${tmp_dir}/empty"
mkdir -p "${empty}"
if "${AUDIT}" --subagent-calls 0 "${empty}" >"${tmp_dir}/empty.out"; then
  fail "empty project should fail"
fi
grep -q "no_active_session" "${tmp_dir}/empty.out" || fail "empty audit should explain failure"

generation="${healthy}/.rdl/sessions/audit"
echo "tampered" >"${generation}/progress.md"
if "${AUDIT}" --subagent-calls 0 "${healthy}" >"${tmp_dir}/drift.out"; then
  fail "derived view drift should fail strict dogfood audit"
fi
grep -q "derived_view_drift" "${tmp_dir}/drift.out" || fail "drift should be reported"

if "${AUDIT}" --subagent-calls 0 "${tmp_dir}/missing" >"${tmp_dir}/missing.out" 2>"${tmp_dir}/missing.err"; then
  fail "non-directory should fail"
fi
grep -q "project root is not a directory" "${tmp_dir}/missing.err" || fail "non-directory error missing"

broken_root="${tmp_dir}/broken-repo"
mkdir -p "${broken_root}/scripts" "${broken_root}/local/research-dev-loop/bin"
cp "${AUDIT}" "${broken_root}/scripts/rdl_dogfood_audit.sh"
cat >"${broken_root}/local/research-dev-loop/bin/rdl" <<'EOF'
#!/bin/sh
echo 'rdl bundled package is missing from the installed skill.' >&2
exit 1
EOF
chmod +x "${broken_root}/local/research-dev-loop/bin/rdl"
if "${broken_root}/scripts/rdl_dogfood_audit.sh" --subagent-calls 0 "${empty}" >"${tmp_dir}/bootstrap.out"; then
  fail "launcher bootstrap failure should fail"
fi
grep -q "bootstrap_error" "${tmp_dir}/bootstrap.out" || fail "bootstrap error code missing"
grep -q "bundled package is missing" "${tmp_dir}/bootstrap.out" || fail "bootstrap stderr missing"

echo "RDL dogfood audit ok"

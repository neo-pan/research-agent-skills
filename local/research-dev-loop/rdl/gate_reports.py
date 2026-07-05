"""Round-local gate report persistence for RDL."""

from __future__ import annotations

from typing import Any

from . import store
from .gate import GateReport
from .session import Session


def write(session: Session, report: GateReport) -> tuple[str, str]:
    """Write structured and human-readable gate reports for the current round."""

    round_dir = session.round_dir()
    json_path = round_dir / "gate-report.json"
    md_path = round_dir / "gate.md"
    store.write_json_atomic(json_path, _json_report(session, report))
    store.write_text_atomic(md_path, _markdown_report(session, report))
    return (str(json_path), str(md_path))


def _json_report(session: Session, report: GateReport) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "session_id": session.state.session_id,
        "round": session.state.round,
        "mode": str(session.state.mode),
        "profile": str(session.state.profile),
        "action": report.action,
        "status": report.status,
        "warnings": list(report.warnings),
        "blockers": [
            {
                "code": blocker.code,
                "file": blocker.file,
                "message": blocker.message,
                "next_action": blocker.next_action,
            }
            for blocker in report.blockers
        ],
        "details": report.details,
    }


def _markdown_report(session: Session, report: GateReport) -> str:
    lines = [
        "# Gate Report",
        "",
        f"Session: {session.state.session_id}",
        f"Round: {session.state.round:03d}",
        f"Action: {report.action}",
        f"Status: {report.status}",
        "",
        "## Findings",
        "",
    ]
    if not report.findings:
        lines.append("No gate findings.")
    else:
        lines.extend(_finding_line(finding) for finding in report.details.get("findings", []))
    lines.extend(
        [
            "",
            "## Warnings",
            "",
        ]
    )
    if report.warnings:
        lines.extend(f"- {warning}" for warning in report.warnings)
    else:
        lines.append("No warnings.")
    lines.append("")
    return "\n".join(lines)


def _finding_line(finding: dict[str, str]) -> str:
    source = finding.get("source", "deterministic")
    return (
        f"- {finding.get('severity', '')} {finding.get('category', '')}/"
        f"{finding.get('code', '')} ({source}): {finding.get('message', '')}"
    )

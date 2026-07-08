"""Command execution for the Python RDL package."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import documents, gate, gate_reports, integrity, memory, memory_report, repair, review_pack, session_memory_edit, summary, templates, transition
from .model import Blocker, CommandResult, RoundProfile, SessionMode, SessionPhase, SessionState, SessionStatus
from .protocol import descriptor
from .session import Session, SessionStore, SessionLockError, acquire_session_lock, valid_session_id


@dataclass(frozen=True)
class CommandIntent:
    command: str
    mode: str | None = None
    profile: str | None = None
    mission_file: str | None = None
    session_id: str | None = None
    session_path: str | None = None
    decision_type: str | None = None
    guard_session_id: str | None = None
    guard_command_id: str | None = None
    reason_parts: tuple[str, ...] = ()
    outcome: str | None = None
    next_mode: str | None = None
    summarize_mode: str | None = None
    summarize_round: int | None = None
    memory_mode: str | None = None
    progress_action: str | None = None
    factor_action: str | None = None
    item: str | None = None
    text: str | None = None
    blocking: str | None = None
    trigger: str | None = None
    reason: str | None = None
    needed: str | None = None
    impact: str | None = None
    section: str | None = None
    value: str | None = None
    review_pack: bool = False


@dataclass(frozen=True)
class _LockedContext:
    action: str
    session: Session
    state: SessionState

    def refresh_after_mutation(self, phase: str, round_number: int) -> CommandResult | None:
        return _refresh_after_mutation(self.action, self.session, self.state, phase, round_number)


def execute(intent: CommandIntent) -> CommandResult:
    if intent.command == "doctor":
        return _doctor(intent.session_id, intent.session_path)
    if intent.command == "handoff":
        return _handoff(intent.session_id, intent.session_path)
    if intent.command == "summarize":
        return _summarize(intent.summarize_mode, intent.summarize_round, intent.session_id, intent.session_path)
    if intent.command == "memory":
        return _memory(intent.memory_mode, intent.session_id, intent.session_path)
    if intent.command == "progress":
        return _progress(intent)
    if intent.command == "factors":
        return _factors(intent)
    if intent.command == "start":
        return _start(intent.mode, intent.profile, intent.mission_file, intent.session_id)
    if intent.command == "status":
        return _status()
    if intent.command == "repair":
        return _repair()
    if intent.command == "next":
        return _next(intent.next_mode, intent.profile)
    if intent.command == "close":
        return _close(intent.outcome)
    if intent.command == "abandon":
        return _abandon(intent.reason_parts)
    if intent.command == "guard-stop":
        return _guard_stop(intent.guard_session_id, intent.guard_command_id)
    if intent.command == "review":
        return _review(intent.review_pack, intent.session_id, intent.session_path)
    if intent.command == "decide":
        return _decide(intent.decision_type)
    raise ValueError(f"unsupported command: {intent.command!r}")


def _start(mode: str | None, profile: str | None, mission_file: str | None, session_id: str | None) -> CommandResult:
    if not mode or not mission_file:
        blocker = Blocker(
            "missing_arguments",
            "",
            "start requires mode and mission file.",
            "rdl start research <mission.md>",
        )
        return CommandResult(
            status="error",
            action="start",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="rdl start research <mission.md>",
        )
    if mode not in {SessionMode.RESEARCH.value, SessionMode.BUILD.value}:
        blocker = Blocker(
            "invalid_mode",
            "",
            "mode must be research or build.",
            "Use rdl start research or rdl start build.",
        )
        return CommandResult(
            status="error",
            action="start",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="Use rdl start research or rdl start build.",
        )
    profile_value = profile or RoundProfile.FULL_REVIEW.value
    profile_blocker = _profile_blocker(mode, profile_value)
    if profile_blocker is not None:
        return CommandResult(
            status="error",
            action="start",
            blockers=(profile_blocker,),
            next_action=profile_blocker.next_action,
        )

    mission_path = Path(mission_file)
    if not mission_path.is_file():
        blocker = Blocker(
            "missing_mission_file",
            mission_file,
            f"mission file not found: {mission_file}",
            "Create the mission file or pass an existing file.",
        )
        return CommandResult(
            status="error",
            action="start",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="Create the mission file or pass an existing file.",
        )

    store = SessionStore.cwd()
    new_session_id = session_id or transition.now_utc().replace("T", "-").replace(":", "").removesuffix("Z")
    if not valid_session_id(new_session_id):
        blocker = Blocker(
            "invalid_session_id",
            "",
            "session id may contain only letters, numbers, dot, underscore, and dash.",
            "Choose a simpler --session-id.",
        )
        return CommandResult(
            status="error",
            action="start",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="Choose a simpler --session-id.",
        )
    session_dir = store.sessions_root / new_session_id
    if session_dir.exists():
        blocker = Blocker(
            "session_already_exists",
            str(session_dir),
            "A session with this id already exists.",
            "Choose a different --session-id.",
        )
        return CommandResult(
            status="blocked",
            action="start",
            session_id=new_session_id,
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="choose a different --session-id",
        )

    try:
        existing = store.active_session()
    except ValueError:
        return CommandResult(
            status="error",
            action="start",
            blockers=(
                Blocker(
                    "multiple_active_sessions",
                    ".rdl/sessions",
                    "Multiple active RDL sessions exist.",
                    "Close or abandon all but one active session.",
                ),
            ),
            next_action="repair RDL session metadata",
        )
    if existing is not None:
        audit = existing.audit()
        if audit.errors:
            state = existing.state
            return _state_result(
                "error",
                "start",
                state,
                blockers=audit.errors,
                next_action="repair RDL session metadata",
                round_number=state.round if state.round > 0 else 0,
            )
        state = existing.state
        blocker = Blocker(
            "active_session_exists",
            str(existing.root / "state.json"),
            "An active RDL session already exists.",
            "Run rdl status, then close or abandon the active session before starting another.",
        )
        return _state_result(
            "blocked",
            "start",
            state,
            blockers=(blocker,),
            next_action="rdl status",
        )

    try:
        session = store.create_session(mode, mission_path, new_session_id, profile_value)
    except FileNotFoundError as exc:
        return _template_write_error("start", _synthetic_state(new_session_id, mode, profile_value), "plan", 1, exc)
    except Exception as exc:
        state = _synthetic_state(new_session_id, mode, profile_value)
        return _integrity_refresh_error("start", state, "plan", 1, exc)

    state = session.state
    return _state_result(
        "ok",
        "start",
        state,
        next_action=str(session.round_dir(1) / "prompt.md"),
    )


def _status() -> CommandResult:
    try:
        session = SessionStore.cwd().active_session()
    except ValueError:
        return CommandResult(
            status="error",
            action="status",
            blockers=(
                Blocker(
                    "multiple_active_sessions",
                    ".rdl/sessions",
                    "Multiple active RDL sessions exist.",
                    "Close or abandon all but one active session.",
                ),
            ),
            next_action="repair RDL session metadata",
        )

    if session is None:
        return CommandResult(status="ok", action="status", next_action="rdl start research <mission.md>")

    state = session.state
    state_errors = session.state_errors()
    if state_errors:
        return _state_result(
            "error",
            "status",
            state,
            blockers=state_errors,
            next_action="repair RDL session metadata",
            round_number=state.round if state.round > 0 else 0,
        )
    return _state_result(
        "ok",
        "status",
        state,
        next_action=str(state.status),
    )


def _synthetic_state(session_id: str, mode: str, profile: str = RoundProfile.FULL_REVIEW.value) -> SessionState:
    return SessionState(
        schema_version=1,
        session_id=session_id,
        mode=SessionMode(mode),
        profile=RoundProfile(profile),
        phase=SessionPhase.PLAN,
        round=1,
        status=SessionStatus.ACTIVE,
        mission_file="mission.md",
    )


def _state_result(
    status: str,
    action: str,
    state: SessionState,
    *,
    blockers: Sequence[Blocker] = (),
    next_action: str = "",
    phase: str | None = None,
    round_number: int | None = None,
    mode: str | None = None,
    profile: str | None = None,
    warnings: Sequence[str] = (),
    details: dict[str, object] | None = None,
) -> CommandResult:
    blocker_tuple = tuple(blockers)
    return CommandResult(
        status=status,
        action=action,
        session_id=state.session_id,
        mode=str(state.mode) if mode is None else mode,
        profile=str(state.profile) if profile is None else profile,
        phase=str(state.phase) if phase is None else str(phase),
        round=state.round if round_number is None else round_number,
        missing=_missing_from_blockers(blocker_tuple),
        warnings=tuple(warnings),
        blockers=blocker_tuple,
        next_action=next_action,
        details={} if details is None else details,
    )


def _doctor(session_id: str | None = None, session_path: str | None = None) -> CommandResult:
    loaded = _selected_session_result("doctor", session_id, session_path)
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded

    gate_report = gate.run(session, "doctor")
    blockers = gate_report.blockers
    warnings = gate_report.warnings
    details = _gate_details(gate_report)
    state = session.state
    if blockers:
        return _state_result(
            "blocked",
            "doctor",
            state,
            blockers=blockers,
            warnings=warnings,
            next_action="complete missing RDL records",
            details=details,
        )

    return _state_result(
        "ok",
        "doctor",
        state,
        warnings=warnings,
        next_action="rdl review",
        details=details,
    )


def _gate_details(report: gate.GateReport) -> dict[str, object]:
    return {"gate": report.details}


def _selector_requires_check(action: str) -> CommandResult:
    blocker = Blocker(
        "session_selector_requires_check",
        "",
        f"{action} session selectors are only supported in check mode.",
        f"Use rdl {action} --check with a session selector, or run write mode on the active session.",
    )
    return CommandResult(
        status="error",
        action=action,
        blockers=(blocker,),
        missing=_missing_from_blockers((blocker,)),
        next_action=blocker.next_action,
    )


def _repair() -> CommandResult:
    loaded = _active_session_result("repair", audit=False)
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded
    state = session.state

    result = repair.repair(session)
    if result.errors:
        return _state_result(
            "error",
            "repair",
            state,
            blockers=result.errors,
            next_action="restore unsafe files before repair",
        )
    if result.blockers:
        next_action = (
            "retry after lock clears"
            if any(blocker.code in {"session_locked", "stale_lock"} for blocker in result.blockers)
            else "restore unsafe files before repair"
        )
        return _state_result(
            "blocked",
            "repair",
            state,
            blockers=result.blockers,
            next_action=next_action,
        )

    repaired_session = SessionStore.cwd().load_session(session.root)
    audit = repaired_session.audit()
    if audit.errors:
        return _state_result(
            "error",
            "repair",
            state,
            blockers=audit.errors,
            next_action="inspect repaired session",
        )
    if audit.blockers:
        return _state_result(
            "blocked",
            "repair",
            state,
            blockers=audit.blockers,
            next_action="inspect repaired session",
        )

    return _state_result(
        "ok",
        "repair",
        state,
        next_action=",".join(result.repaired),
    )


def _summarize(mode: str | None, through_round: int | None, session_id: str | None = None, session_path: str | None = None) -> CommandResult:
    summarize_mode = mode or "check"
    if summarize_mode not in {"check", "write"}:
        blocker = Blocker(
            "invalid_summarize_mode",
            "",
            "summarize mode must be check or write.",
            "Use rdl summarize --check or rdl summarize --write.",
        )
        return CommandResult(
            status="error",
            action="summarize",
            blockers=(blocker,),
            next_action="Use rdl summarize --check or rdl summarize --write.",
        )
    if summarize_mode == "write" and (session_id or session_path):
        return _selector_requires_check("summarize")
    if summarize_mode == "write":
        return _run_locked_session("summarize", lambda context: _summarize_write_locked(context, through_round))

    loaded = _selected_session_result("summarize", session_id, session_path)
    if isinstance(loaded, CommandResult):
        return loaded
    state = loaded.state
    summary_plan = summary.check(loaded, through_round)
    if summary_plan.blockers:
        return _state_result(
            "error",
            "summarize",
            state,
            blockers=summary_plan.blockers,
            next_action="pass a valid --round",
            details=summary_plan.details("needs_update"),
        )
    status = "up_to_date" if summary.progress_up_to_date(loaded, summary_plan) else "needs_update"
    return _state_result(
        "ok",
        "summarize",
        state,
        next_action="rdl summarize --write" if status == "needs_update" else "rdl doctor",
        details=summary_plan.details(status),
    )


def _summarize_write_locked(context: _LockedContext, through_round: int | None) -> CommandResult:
    session = context.session
    state = context.state
    summary_plan = summary.plan(session, through_round)
    if summary_plan.blockers:
        return _state_result(
            "error",
            "summarize",
            state,
            blockers=summary_plan.blockers,
            next_action="pass a valid --round",
            details=summary_plan.details("needs_update"),
        )

    blockers = summary.write(session, summary_plan)
    if blockers:
        return _state_result(
            "blocked",
            "summarize",
            state,
            blockers=blockers,
            next_action="restore canonical progress.md tables",
            details=summary_plan.details("needs_update"),
        )

    refresh_error = context.refresh_after_mutation(str(state.phase), state.round)
    if refresh_error is not None:
        return refresh_error

    return _state_result(
        "ok",
        "summarize",
        state,
        next_action="rdl doctor",
        details=summary_plan.details("written"),
    )


def _memory(mode: str | None, session_id: str | None = None, session_path: str | None = None) -> CommandResult:
    memory_mode = mode or "check"
    if memory_mode not in {"check", "write"}:
        blocker = Blocker(
            "invalid_memory_mode",
            "",
            "memory mode must be check or write.",
            "Use rdl memory --check or rdl memory --write.",
        )
        return CommandResult(
            status="error",
            action="memory",
            blockers=(blocker,),
            next_action=blocker.next_action,
        )
    if memory_mode == "write" and (session_id or session_path):
        return _selector_requires_check("memory")
    if memory_mode == "write":
        return _run_locked_session("memory", _memory_write_locked)

    loaded = _selected_session_result("memory", session_id, session_path)
    if isinstance(loaded, CommandResult):
        return loaded
    state = loaded.state
    report, summary_plan = memory_report.check(loaded)
    if summary_plan.blockers:
        return _state_result(
            "error",
            "memory",
            state,
            blockers=summary_plan.blockers,
            next_action="inspect session round state",
            details=report.details("needs_attention"),
        )
    return _state_result(
        "ok",
        "memory",
        state,
        next_action=_memory_next_action(report),
        details=report.details(),
    )


def _memory_write_locked(context: _LockedContext) -> CommandResult:
    session = context.session
    state = context.state
    report, summary_plan = memory_report.check(session)
    if summary_plan.blockers:
        return _state_result(
            "error",
            "memory",
            state,
            blockers=summary_plan.blockers,
            next_action="inspect session round state",
            details=report.details("needs_attention"),
        )

    wrote_summary = not summary.progress_up_to_date(session, summary_plan) and summary_plan.total_rows > 0
    if wrote_summary:
        blockers = summary.write(session, summary_plan)
        if blockers:
            return _state_result(
                "blocked",
                "memory",
                state,
                blockers=blockers,
                next_action="restore canonical progress.md tables",
                details=report.details("needs_attention"),
            )

        refresh_error = context.refresh_after_mutation(str(state.phase), state.round)
        if refresh_error is not None:
            return refresh_error

    refreshed = SessionStore.cwd().load_session(session.root)
    written_report = memory_report.report_after_write(refreshed, summary.plan(refreshed))
    return _state_result(
        "ok",
        "memory",
        state,
        next_action=_memory_next_action(written_report),
        details=written_report.details("written" if wrote_summary else written_report.memory_status),
    )


def _memory_next_action(report: memory_report.MemoryReport) -> str:
    if any(action.startswith("Run rdl memory --write") for action in report.suggested_actions):
        return "rdl memory --write"
    if any(action.startswith("Record progress memory with rdl progress") for action in report.suggested_actions):
        return "rdl progress active|blocked|deferred|none"
    if any(action.startswith("Record factor memory with rdl factors") for action in report.suggested_actions):
        return "rdl factors set|note"
    if report.quality_warnings:
        return report.quality_warnings[0].next_action
    if report.memory_status == "healthy":
        return "rdl doctor"
    return "update session memory manually"


def _progress(intent: CommandIntent) -> CommandResult:
    action = intent.progress_action or ""
    if action not in {"active", "blocked", "deferred", "none"}:
        blocker = Blocker(
            "invalid_progress_action",
            "",
            "progress action must be active, blocked, deferred, or none.",
            "Use rdl progress active, blocked, deferred, or none.",
        )
        return CommandResult(status="error", action="progress", blockers=(blocker,), next_action=blocker.next_action)

    blockers = _progress_argument_blockers(intent)
    if blockers:
        return CommandResult(
            status="error",
            action="progress",
            blockers=tuple(blockers),
            missing=_missing_from_blockers(blockers),
            next_action=blockers[0].next_action,
        )
    return _run_locked_session("progress", lambda context: _progress_locked(context, intent))


def _progress_locked(context: _LockedContext, intent: CommandIntent) -> CommandResult:
    state = context.state
    action = intent.progress_action or ""
    if action == "active":
        section = "Active"
        cells = (
            intent.item or "",
            intent.mode or str(state.mode),
            intent.text or "",
            intent.blocking or "no",
            intent.trigger or "",
        )
    elif action == "blocked":
        section = "Blocked"
        cells = (intent.item or "", intent.reason or "", intent.needed or "", intent.impact or "")
    elif action == "deferred":
        section = "Deferred"
        cells = (intent.item or "", intent.reason or "", intent.trigger or "")
    else:
        section = intent.section or ""
        cells = _none_progress_cells(section, intent.reason or "", state)

    edit_result, blockers = session_memory_edit.append_progress_row(context.session.root, section, cells)
    if blockers:
        return _state_result(
            "blocked",
            "progress",
            state,
            blockers=blockers,
            next_action="restore canonical progress.md",
        )

    refresh_error = context.refresh_after_mutation(str(state.phase), state.round)
    if refresh_error is not None:
        return refresh_error

    return _state_result(
        "ok",
        "progress",
        state,
        next_action="rdl memory --check",
        details={} if edit_result is None else edit_result.details(),
    )


def _factors(intent: CommandIntent) -> CommandResult:
    action = intent.factor_action or "set"
    if action not in {"set", "note"}:
        blocker = Blocker(
            "invalid_factor_action",
            "",
            "factors action must be set or note.",
            "Use rdl factors set or rdl factors note.",
        )
        return CommandResult(status="error", action="factors", blockers=(blocker,), next_action=blocker.next_action)

    blockers = _factors_argument_blockers(intent)
    if blockers:
        return CommandResult(
            status="error",
            action="factors",
            blockers=tuple(blockers),
            missing=_missing_from_blockers(blockers),
            next_action=blockers[0].next_action,
        )
    return _run_locked_session("factors", lambda context: _factors_locked(context, intent))


def _factors_locked(context: _LockedContext, intent: CommandIntent) -> CommandResult:
    state = context.state
    action = intent.factor_action or "set"
    if action == "set":
        edit_result, blockers = session_memory_edit.set_factor(context.session.root, intent.section or "", intent.value or "")
    else:
        edit_result, blockers = session_memory_edit.append_factor_note(context.session.root, intent.section or "", intent.value or "")
    if blockers:
        return _state_result(
            "blocked",
            "factors",
            state,
            blockers=blockers,
            next_action="restore canonical factors.md",
        )

    refresh_error = context.refresh_after_mutation(str(state.phase), state.round)
    if refresh_error is not None:
        return refresh_error

    return _state_result(
        "ok",
        "factors",
        state,
        next_action="rdl memory --check",
        details={} if edit_result is None else edit_result.details(),
    )


def _progress_argument_blockers(intent: CommandIntent) -> list[Blocker]:
    action = intent.progress_action or ""
    if action == "active":
        blockers = _required_memory_values(
            (
                (intent.item, "--item"),
                (intent.text, "--text"),
                (intent.trigger, "--trigger"),
            )
        )
        if intent.mode is not None and intent.mode not in {SessionMode.RESEARCH.value, SessionMode.BUILD.value}:
            blockers.append(
                Blocker(
                    "invalid_mode",
                    "",
                    "mode must be research or build.",
                    "Use --mode research or --mode build.",
                )
            )
        if intent.blocking is not None and intent.blocking not in {"yes", "no"}:
            blockers.append(
                Blocker(
                    "invalid_blocking_value",
                    "",
                    "blocking must be yes or no.",
                    "Use --blocking yes or --blocking no.",
                )
            )
        return blockers
    if action == "blocked":
        return _required_memory_values(
            (
                (intent.item, "--item"),
                (intent.reason, "--reason"),
                (intent.needed, "--needed"),
                (intent.impact, "--impact"),
            )
        )
    if action == "deferred":
        return _required_memory_values(((intent.item, "--item"), (intent.reason, "--reason"), (intent.trigger, "--trigger")))
    return _required_memory_values(((intent.section, "--section"), (intent.reason, "--reason"))) + _progress_section_blockers(intent.section)


def _factors_argument_blockers(intent: CommandIntent) -> list[Blocker]:
    return _required_memory_values(((intent.section, "--section"), (intent.value, "--value"))) + _factor_section_blockers(intent.section)


def _required_memory_values(values: Sequence[tuple[str | None, str]]) -> list[Blocker]:
    blockers: list[Blocker] = []
    for value, option in values:
        blocker = session_memory_edit.value_blocker(value, option)
        if blocker is not None:
            blockers.append(blocker)
    return blockers


def _progress_section_blockers(section: str | None) -> list[Blocker]:
    if section is None or section in session_memory_edit.PROGRESS_MANUAL_SECTIONS:
        return []
    return [
        Blocker(
            "invalid_progress_section",
            "",
            "progress section must be Active, Blocked, or Deferred.",
            "Use --section Active, Blocked, or Deferred.",
        )
    ]


def _factor_section_blockers(section: str | None) -> list[Blocker]:
    if section is None or section in session_memory_edit.FACTOR_SECTIONS:
        return []
    return [
        Blocker(
            "invalid_factor_section",
            "",
            "factor section is not a canonical RDL factor heading.",
            "Use a canonical factors.md section heading.",
        )
    ]


def _none_progress_cells(section: str, reason: str, state: SessionState) -> tuple[str, ...]:
    if section == "Active":
        return ("no-active-items", str(state.mode), f"none: {reason}", "no", "-")
    if section == "Blocked":
        return ("no-blocked-items", reason, "none", "none")
    return ("no-deferred-items", reason, "-")


def _handoff(session_id: str | None = None, session_path: str | None = None) -> CommandResult:
    loaded = _selected_session_result("handoff", session_id, session_path)
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded
    state = session.state
    gate_report = gate.run(session, "handoff")
    prompt_context = memory.prompt_context(session)
    report, _summary_plan = memory_report.check(session)
    handoff_status = "ready" if report.memory_status == "healthy" else "needs_attention"
    suggested_actions = list(report.suggested_actions) or ["rdl doctor"]
    details = {
        "handoff_status": handoff_status,
        "current_focus": prompt_context.claim_or_capability,
        "open_questions": prompt_context.open_questions,
        "known_evidence_gaps": prompt_context.known_evidence_gaps,
        "directions_tried": prompt_context.directions_tried,
        "staleness_watch": prompt_context.staleness_watch,
        "next_smallest_step": prompt_context.next_smallest_step,
        "last_decision": _last_decision_details(session),
        "latest_completed_decision": _latest_completed_decision_details(session),
        "memory": report.details(),
        "suggested_actions": suggested_actions,
        "gate": gate_report.details,
    }
    return _state_result(
        "ok",
        "handoff",
        state,
        warnings=gate_report.warnings,
        next_action="rdl doctor" if handoff_status == "ready" else _memory_next_action(report),
        details=details,
    )


def _last_decision_details(session: Session) -> dict[str, str]:
    return _decision_details(session.round_dir() / "decision.md")


def _latest_completed_decision_details(session: Session) -> dict[str, object]:
    for round_number in range(session.state.round, 0, -1):
        decision_file = session.round_dir(round_number) / "decision.md"
        if documents.field(decision_file, "Decision"):
            details: dict[str, object] = {"round": round_number}
            details.update(_decision_details(decision_file))
            return details

    details = {"round": 0}
    details.update(_decision_details(Path()))
    return details


def _decision_details(decision_file: Path) -> dict[str, str]:
    return {
        "decision": _field_or_none_recorded(decision_file, "Decision"),
        "closes": _field_or_none_recorded(decision_file, "Closes"),
        "evidence": _field_or_none_recorded(decision_file, "Evidence"),
        "uncertainty": _field_or_none_recorded(decision_file, "Uncertainty"),
        "what_remains_unknown": _field_or_none_recorded(decision_file, "What remains unknown"),
        "recommended_next_loop": _field_or_none_recorded(decision_file, "Recommended next loop"),
    }


def _field_or_none_recorded(path: Path, name: str) -> str:
    value = documents.field(path, name) if name in _SINGLE_LINE_DETAIL_FIELDS else documents.field_text(path, name)
    return value if value else memory.NONE_RECORDED


_SINGLE_LINE_DETAIL_FIELDS = {
    "Decision",
    "Closes",
    "Recommended next loop",
}


def _next(next_mode: str | None = None, next_profile: str | None = None) -> CommandResult:
    if next_mode is not None and next_mode not in {SessionMode.RESEARCH.value, SessionMode.BUILD.value}:
        blocker = Blocker(
            "invalid_mode",
            "",
            "mode must be research or build.",
            "Use rdl next --mode research or rdl next --mode build.",
        )
        return CommandResult(
            status="error",
            action="next",
            blockers=(blocker,),
            next_action="Use rdl next --mode research or rdl next --mode build.",
        )
    if next_profile is not None and next_profile not in {profile.value for profile in RoundProfile}:
        blocker = Blocker(
            "invalid_profile",
            "",
            "profile must be full-review, checkpoint, or build-update.",
            "Use rdl next --profile full-review, checkpoint, or build-update.",
        )
        return CommandResult(
            status="error",
            action="next",
            blockers=(blocker,),
            next_action=blocker.next_action,
        )
    return _run_locked_session("next", lambda context: _next_locked(context, next_mode, next_profile))


def _next_locked(context: _LockedContext, next_mode: str | None, next_profile: str | None) -> CommandResult:
    session = context.session
    state = context.state
    target_mode = next_mode or str(state.mode)
    target_profile = next_profile or str(state.profile)
    profile_blocker = _profile_blocker(target_mode, target_profile)
    if profile_blocker is not None:
        return _state_result(
            "blocked",
            "next",
            state,
            blockers=(profile_blocker,),
            next_action=profile_blocker.next_action,
        )

    gate_report = gate.run(session, "advance", next_mode=next_mode)
    blockers = gate_report.blockers
    if blockers:
        return _state_result(
            "blocked",
            "next",
            state,
            blockers=blockers,
            warnings=gate_report.warnings,
            next_action="complete current round review and decision",
            details=_gate_details(gate_report),
        )

    transition_blocker = _advance_transition_blocker(session)
    if transition_blocker is not None:
        return _state_result(
            "blocked",
            "next",
            state,
            blockers=(transition_blocker,),
            warnings=gate_report.warnings,
            next_action="inspect existing next round",
            details=_gate_details(gate_report),
        )

    session, gate_report, refresh_result = _refresh_transition_summary(
        context,
        gate_report,
        "next",
        "advance",
        next_mode=next_mode,
        blocked_next_action="restore canonical progress.md tables",
    )
    if refresh_result is not None:
        return refresh_result

    persist_error = _write_gate_report(context, gate_report, "persist gate report before advancing")
    if persist_error is not None:
        return persist_error

    try:
        result = transition.advance(session, next_mode, next_profile)
    except transition.TransitionBlocked as exc:
        refresh_error = context.refresh_after_mutation(str(state.phase), state.round)
        if refresh_error is not None:
            return refresh_error
        return _state_result(
            "blocked",
            "next",
            state,
            blockers=(exc.blocker,),
            warnings=gate_report.warnings,
            next_action="inspect existing next round",
            details=_gate_details(gate_report),
        )

    refresh_error = context.refresh_after_mutation(result.phase, result.round)
    if refresh_error is not None:
        return refresh_error

    return _state_result(
        "ok",
        "next",
        state,
        phase=result.phase,
        round_number=result.round,
        mode=result.mode,
        profile=result.profile,
        warnings=gate_report.warnings,
        next_action=result.next_action,
        details=_gate_details(gate_report),
    )


def _review(pack: bool = False, session_id: str | None = None, session_path: str | None = None) -> CommandResult:
    if (session_id or session_path) and not pack:
        blocker = Blocker(
            "session_selector_requires_pack",
            "",
            "review session selectors are only supported with --pack.",
            "Use rdl review --pack --session-id <id> --json.",
        )
        return CommandResult(
            status="error",
            action="review",
            blockers=(blocker,),
            missing=_missing_from_blockers((blocker,)),
            next_action=blocker.next_action,
        )
    if pack:
        return _review_pack(session_id, session_path)
    return _run_locked_session("review", _review_locked)


def _review_pack(session_id: str | None = None, session_path: str | None = None) -> CommandResult:
    loaded = _selected_session_result("review", session_id, session_path)
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded
    gate_report = gate.run(session, "doctor")
    pack = review_pack.build(session, "review", gate_report)
    return _state_result(
        "ok",
        "review",
        session.state,
        warnings=gate_report.warnings,
        next_action="send details.review_pack to the reviewer agent",
        details={
            "review_pack": pack.as_dict(),
            "gate": gate_report.details,
        },
    )


def _review_locked(context: _LockedContext) -> CommandResult:
    session = context.session
    state = context.state
    review_file = session.round_dir() / "review.md"

    if not review_file.is_file():
        try:
            templates.copy_template("review.md", review_file)
        except Exception as exc:
            return _template_write_error("review", state, str(state.phase), state.round, exc)
        refresh_error = context.refresh_after_mutation(str(state.phase), state.round)
        if refresh_error is not None:
            return refresh_error
        return _state_result(
            "ok",
            "review",
            state,
            next_action=str(review_file),
        )

    blockers = tuple(documents.validate("review", review_file))
    if blockers:
        return _state_result(
            "blocked",
            "review",
            state,
            blockers=blockers,
            next_action="complete review.md",
        )

    return _state_result(
        "ok",
        "review",
        state,
        next_action="rdl decide <decision-type>",
    )


def _decide(decision_type: str | None) -> CommandResult:
    if not decision_type:
        blocker = Blocker(
            "missing_decision_type",
            "",
            "decide requires a decision type.",
            "rdl decide continue",
        )
        return CommandResult(
            status="error",
            action="decide",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="rdl decide continue",
        )
    if not descriptor.value_allowed("decision-type", decision_type):
        blocker = Blocker(
            "invalid_decision_type",
            "",
            f"unsupported decision type: {decision_type}",
            "Use a planned RDL decision type.",
        )
        return CommandResult(
            status="error",
            action="decide",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="Use a planned RDL decision type.",
        )

    return _run_locked_session("decide", lambda context: _decide_locked(context, decision_type))


def _decide_locked(context: _LockedContext, decision_type: str) -> CommandResult:
    session = context.session
    state = context.state
    decision_file = session.round_dir() / "decision.md"
    expected_closes = descriptor.expected_closes(state.mode)

    if not decision_file.is_file():
        try:
            templates.write_decision(decision_file, decision_type, expected_closes)
        except Exception as exc:
            return _template_write_error("decide", state, str(state.phase), state.round, exc)
        refresh_error = context.refresh_after_mutation(str(state.phase), state.round)
        if refresh_error is not None:
            return refresh_error
        return _state_result(
            "ok",
            "decide",
            state,
            next_action=str(decision_file),
        )

    blockers = list(documents.validate("decision", decision_file, {"expected_closes": expected_closes}))
    if documents.field(decision_file, "Decision") != decision_type:
        blockers.append(
            Blocker(
                "decision_type_mismatch",
                f"{decision_file}#Decision",
                "Decision does not match the requested decision type.",
                "Run rdl decide with the recorded decision type or update decision.md.",
            )
        )
    if blockers:
        return _state_result(
            "blocked",
            "decide",
            state,
            blockers=tuple(blockers),
            next_action="complete decision.md",
        )

    return _state_result(
        "ok",
        "decide",
        state,
        next_action="rdl next",
    )


def _close(outcome: str | None) -> CommandResult:
    if outcome is not None and not descriptor.value_allowed("close-outcome", outcome):
        blocker = Blocker(
            "invalid_close_outcome",
            "",
            f"unsupported close outcome: {outcome}",
            "Use rdl close positive, negative, or inconclusive.",
        )
        return CommandResult(
            status="error",
            action="close",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="Use rdl close positive, negative, or inconclusive.",
        )

    if outcome is None:
        loaded = _active_session_result("close", audit=False)
        if isinstance(loaded, CommandResult):
            if loaded.blockers and loaded.blockers[0].code == "no_active_session":
                return _missing_close_outcome_result()
            return loaded
        outcome = descriptor.close_outcome_for_decision(documents.field(loaded.round_dir() / "decision.md", "Decision"))
        if not outcome:
            return _missing_close_outcome_result()

    return _run_locked_session("close", lambda context: _close_locked(context, outcome))


def _close_locked(context: _LockedContext, outcome: str) -> CommandResult:
    session = context.session
    state = context.state
    gate_report = gate.run(session, "close", outcome=outcome)
    blockers = gate_report.blockers

    if blockers:
        return _state_result(
            "blocked",
            "close",
            state,
            blockers=blockers,
            warnings=gate_report.warnings,
            next_action="complete close records",
            details=_gate_details(gate_report),
        )

    session, gate_report, refresh_result = _refresh_transition_summary(
        context,
        gate_report,
        "close",
        "close",
        outcome=outcome,
        blocked_next_action="restore canonical progress.md tables",
    )
    if refresh_result is not None:
        return refresh_result

    persist_error = _write_gate_report(context, gate_report, "persist gate report before closing")
    if persist_error is not None:
        return persist_error

    result = transition.close(session, outcome)
    refresh_error = context.refresh_after_mutation(result.phase, result.round)
    if refresh_error is not None:
        return refresh_error

    return _state_result(
        "ok",
        "close",
        state,
        phase=result.phase,
        round_number=result.round,
        warnings=gate_report.warnings,
        next_action=result.next_action,
        details=_gate_details(gate_report),
    )


def _missing_close_outcome_result() -> CommandResult:
    blocker = Blocker(
        "missing_close_outcome",
        "",
        "close requires positive, negative, or inconclusive unless decision.md records a close decision.",
        "Run rdl decide close-positive or pass rdl close positive.",
    )
    return CommandResult(
        status="error",
        action="close",
        missing=_missing_from_blockers((blocker,)),
        blockers=(blocker,),
        next_action=blocker.next_action,
    )


def _advance_transition_blocker(session: Session) -> Blocker | None:
    next_round = session.state.round + 1
    if session.round_dir(next_round).exists():
        return Blocker(
            "next_round_exists",
            f"rounds/{next_round:03d}",
            "Next round directory already exists.",
            "Inspect the existing next round before advancing.",
        )
    return None


def _refresh_transition_summary(
    context: _LockedContext,
    gate_report: gate.GateReport,
    command_action: str,
    gate_action: str,
    *,
    next_mode: str | None = None,
    outcome: str | None = None,
    blocked_next_action: str,
) -> tuple[Session, gate.GateReport, CommandResult | None]:
    session = context.session
    state = context.state
    summary_plan = summary.plan(session)
    if summary_plan.blockers or summary_plan.total_rows == 0 or summary.progress_up_to_date(session, summary_plan):
        return session, gate_report, None

    blockers = summary.write(session, summary_plan)
    if blockers:
        return (
            session,
            gate_report,
            _state_result(
                "blocked",
                command_action,
                state,
                blockers=blockers,
                warnings=gate_report.warnings,
                next_action=blocked_next_action,
                details=_gate_details(gate_report),
            ),
        )

    refresh_error = context.refresh_after_mutation(str(state.phase), state.round)
    if refresh_error is not None:
        return session, gate_report, refresh_error

    refreshed = SessionStore.cwd().load_session(session.root)
    return refreshed, gate.run(refreshed, gate_action, next_mode=next_mode, outcome=outcome), None


def _abandon(reason_parts: Sequence[str]) -> CommandResult:
    reason = " ".join(reason_parts).strip()
    if not reason:
        blocker = Blocker(
            "missing_abandon_reason",
            "",
            "abandon requires a non-empty reason.",
            "rdl abandon <reason>",
        )
        return CommandResult(
            status="error",
            action="abandon",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="rdl abandon <reason>",
        )

    return _run_locked_session("abandon", lambda context: _abandon_locked(context, reason))


def _abandon_locked(context: _LockedContext, reason: str) -> CommandResult:
    session = context.session
    state = context.state

    result = transition.abandon(session, reason)
    refresh_error = context.refresh_after_mutation(result.phase, result.round)
    if refresh_error is not None:
        return refresh_error

    return _state_result(
        "ok",
        "abandon",
        state,
        phase=result.phase,
        round_number=result.round,
        next_action=result.next_action,
    )


def _guard_stop(guard_session_id: str | None, guard_command_id: str | None) -> CommandResult:
    try:
        session = SessionStore.cwd().active_session()
    except ValueError:
        return CommandResult(
            status="error",
            action="guard-stop",
            blockers=(
                Blocker(
                    "multiple_active_sessions",
                    ".rdl/sessions",
                    "Multiple active RDL sessions exist.",
                    "Close or abandon all but one active session.",
                ),
            ),
            next_action="repair RDL session metadata",
        )

    if session is None:
        return CommandResult(status="ok", action="guard-stop", next_action="allow")

    state = session.state
    if guard_session_id and guard_session_id != state.session_id:
        return _state_result(
            "ok",
            "guard-stop",
            state,
            next_action="allow",
        )
    if guard_command_id and guard_command_id == state.last_guard_command_id:
        return _state_result(
            "ok",
            "guard-stop",
            state,
            next_action="allow",
        )

    return _run_locked_session(
        "guard-stop",
        lambda context: _guard_stop_locked(context.session, guard_session_id, guard_command_id),
        session=session,
        audit=False,
    )


def _guard_stop_locked(session: Session, guard_session_id: str | None, guard_command_id: str | None) -> CommandResult:
    state = session.state

    audit = session.audit()
    if audit.errors:
        return _state_result(
            "error",
            "guard-stop",
            state,
            blockers=audit.errors,
            next_action="block",
            round_number=state.round if state.round > 0 else 0,
        )
    if audit.blockers:
        return _state_result(
            "blocked",
            "guard-stop",
            state,
            blockers=audit.blockers,
            next_action="block",
        )

    gate_report = _guard_stop_gate(session)
    blockers = gate_report.blockers
    if blockers:
        return _state_result(
            "blocked",
            "guard-stop",
            state,
            blockers=blockers,
            warnings=gate_report.warnings,
            next_action="block",
            details=_gate_details(gate_report),
        )

    persist_error = _write_gate_report_for_session("guard-stop", session, state, gate_report, "persist gate report before guard transition")
    if persist_error is not None:
        return persist_error

    try:
        result = transition.from_decision(session)
    except transition.TransitionBlocked as exc:
        refresh_error = _refresh_after_mutation("guard-stop", session, state, str(state.phase), state.round)
        if refresh_error is not None:
            return refresh_error
        return _state_result(
            "blocked",
            "guard-stop",
            state,
            blockers=(exc.blocker,),
            warnings=gate_report.warnings,
            next_action="block",
            details=_gate_details(gate_report),
        )

    if (guard_session_id and guard_session_id != state.guard_session_id) or (guard_command_id and guard_command_id != state.last_guard_command_id):
        transition.mark_guard_seen(SessionStore.cwd().load_session(session.root), guard_session_id, guard_command_id)

    refresh_error = _refresh_after_mutation("guard-stop", session, state, result.phase, result.round)
    if refresh_error is not None:
        return refresh_error

    return _state_result(
        "ok",
        "guard-stop",
        state,
        phase=result.phase,
        round_number=result.round,
        warnings=gate_report.warnings,
        next_action=result.next_action,
        details=_gate_details(gate_report),
    )


def _guard_stop_gate(session: Session) -> gate.GateReport:
    decision = documents.field(session.round_dir() / "decision.md", "Decision")
    outcome = descriptor.close_outcome_for_decision(decision)
    if outcome:
        return gate.run(session, "close", outcome=outcome)
    return gate.run(session, "advance")


def _write_gate_report(context: _LockedContext, report: gate.GateReport, next_action: str) -> CommandResult | None:
    return _write_gate_report_for_session(context.action, context.session, context.state, report, next_action)


def _write_gate_report_for_session(
    action: str,
    session: Session,
    state: SessionState,
    report: gate.GateReport,
    next_action: str,
) -> CommandResult | None:
    try:
        gate_reports.write(session, report)
    except Exception as exc:
        blocker = Blocker(
            "gate_report_write_failed",
            str(session.round_dir()),
            f"Gate report write failed: {exc}",
            "Inspect round-local gate report files and retry.",
        )
        return _state_result(
            "error",
            action,
            state,
            blockers=(blocker,),
            warnings=report.warnings,
            next_action=next_action,
            details=_gate_details(report),
        )
    return None


def _run_locked_session(
    action: str,
    body: Callable[[_LockedContext], CommandResult],
    *,
    session: Session | None = None,
    audit: bool = True,
) -> CommandResult:
    loaded = session if session is not None else _active_session_result(action, audit=False)
    if isinstance(loaded, CommandResult):
        return loaded
    state = loaded.state
    try:
        with acquire_session_lock(loaded, action):
            locked_session = SessionStore.cwd().load_session(loaded.root)
            state = locked_session.state
            if audit:
                audit_result = locked_session.audit()
                if audit_result.errors:
                    return _state_result(
                        "error",
                        action,
                        state,
                        blockers=audit_result.errors,
                        next_action="repair RDL session metadata",
                        round_number=state.round if state.round > 0 else 0,
                    )
                if audit_result.blockers:
                    return _state_result(
                        "blocked",
                        action,
                        state,
                        blockers=audit_result.blockers,
                        next_action="complete missing RDL records",
                    )
            return body(_LockedContext(action, locked_session, state))
    except SessionLockError as exc:
        return _state_result(
            "blocked",
            action,
            state,
            blockers=(exc.blocker,),
            next_action="retry after lock clears",
            round_number=state.round if state.round > 0 else 0,
        )


def _active_session_result(action: str, audit: bool = True) -> Session | CommandResult:
    try:
        session = SessionStore.cwd().active_session()
    except ValueError:
        return CommandResult(
            status="error",
            action=action,
            blockers=(
                Blocker(
                    "multiple_active_sessions",
                    ".rdl/sessions",
                    "Multiple active RDL sessions exist.",
                    "Close or abandon all but one active session.",
                ),
            ),
            next_action="repair RDL session metadata",
        )

    if session is None:
        return CommandResult(
            status="blocked",
            action=action,
            blockers=(
                Blocker(
                    "no_active_session",
                    ".rdl/sessions",
                    "No active RDL session exists.",
                    "Start an RDL session.",
                ),
            ),
            next_action="rdl start research <mission.md>",
        )

    if not audit:
        return session

    audit = session.audit()
    state = session.state
    if audit.errors:
        return _state_result(
            "error",
            action,
            state,
            blockers=audit.errors,
            next_action="repair RDL session metadata",
            round_number=state.round if state.round > 0 else 0,
        )
    if audit.blockers:
        return _state_result(
            "blocked",
            action,
            state,
            blockers=audit.blockers,
            next_action="complete missing RDL records",
        )

    return session


def _selected_session_result(action: str, session_id: str | None, session_path: str | None, audit: bool = True) -> Session | CommandResult:
    if session_id and session_path:
        blocker = Blocker(
            "ambiguous_session_selector",
            "",
            "Pass either --session-id or --session-path, not both.",
            "Choose one RDL session selector.",
        )
        return CommandResult(
            status="error",
            action=action,
            blockers=(blocker,),
            missing=_missing_from_blockers((blocker,)),
            next_action=blocker.next_action,
        )
    if not session_id and not session_path:
        return _active_session_result(action, audit)

    store_obj = SessionStore.cwd()
    if session_id:
        if not valid_session_id(session_id):
            blocker = Blocker(
                "invalid_session_id",
                "--session-id",
                "Session id contains unsupported characters.",
                "Use a session id containing only letters, numbers, dots, underscores, or hyphens.",
            )
            return CommandResult(
                status="error",
                action=action,
                blockers=(blocker,),
                missing=_missing_from_blockers((blocker,)),
                next_action=blocker.next_action,
            )
        session_dir = store_obj.sessions_root / session_id
    else:
        session_dir = Path(str(session_path))
        if not session_dir.is_absolute():
            session_dir = Path.cwd() / session_dir

    if not session_dir.is_dir():
        blocker = Blocker(
            "missing_session",
            str(session_dir),
            "RDL session not found.",
            "Pass an existing .rdl/sessions/<session-id> path or session id.",
        )
        return CommandResult(
            status="blocked",
            action=action,
            blockers=(blocker,),
            missing=_missing_from_blockers((blocker,)),
            next_action=blocker.next_action,
        )

    session = store_obj.load_session(session_dir)
    if not audit:
        return session

    audit_result = session.audit()
    state = session.state
    if audit_result.errors:
        return _state_result(
            "error",
            action,
            state,
            blockers=audit_result.errors,
            next_action="repair RDL session metadata",
            round_number=state.round if state.round > 0 else 0,
        )
    if audit_result.blockers:
        return _state_result(
            "blocked",
            action,
            state,
            blockers=audit_result.blockers,
            next_action="complete missing RDL records",
        )

    return session


def _integrity_refresh_error(
    action: str,
    state: SessionState,
    phase: str,
    round_number: int,
    exc: Exception,
) -> CommandResult:
    blocker = Blocker(
        "integrity_refresh_failed",
        "integrity.json",
        f"Integrity refresh failed: {exc}",
        "Inspect the session and run rdl repair when available.",
    )
    return _state_result(
        "error",
        action,
        state,
        phase=phase,
        round_number=round_number,
        blockers=(blocker,),
        next_action="repair RDL session metadata",
    )


def _refresh_after_mutation(
    action: str,
    session: Session,
    state: SessionState,
    phase: str,
    round_number: int,
) -> CommandResult | None:
    try:
        integrity.refresh(SessionStore.cwd().load_session(session.root))
    except Exception as exc:
        return _integrity_refresh_error(action, state, phase, round_number, exc)
    return None


def _template_write_error(
    action: str,
    state: SessionState,
    phase: str,
    round_number: int,
    exc: Exception,
) -> CommandResult:
    blocker = Blocker(
        "template_write_failed",
        "templates",
        f"Template write failed: {exc}",
        "Inspect RDL templates and retry the command.",
    )
    return _state_result(
        "error",
        action,
        state,
        phase=phase,
        round_number=round_number,
        blockers=(blocker,),
        next_action="repair RDL templates",
    )


def _profile_blocker(mode: str, profile: str) -> Blocker | None:
    if profile not in {round_profile.value for round_profile in RoundProfile}:
        return Blocker(
            "invalid_profile",
            "",
            "profile must be full-review, checkpoint, or build-update.",
            "Use full-review, checkpoint, or build-update.",
        )
    if not descriptor.profile_allowed_for_mode(mode, profile):
        return Blocker(
            "invalid_profile_for_mode",
            "",
            "profile is not supported for the selected mode.",
            "Use full-review or checkpoint for research; use any supported profile for build.",
        )
    return None


def _missing_from_blockers(blockers: Sequence[Blocker]) -> tuple[str, ...]:
    missing: list[str] = []
    seen: set[str] = set()
    for blocker in blockers:
        path = blocker.file
        if path and path not in seen:
            seen.add(path)
            missing.append(path)
    return tuple(missing)

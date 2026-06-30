"""Command execution for the Python RDL package."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import documents, integrity, readiness, repair, templates, transition
from .model import Blocker, CommandResult, SessionMode, SessionPhase, SessionState, SessionStatus
from .protocol import descriptor
from .session import Session, SessionStore, SessionLockError, acquire_session_lock, valid_session_id


@dataclass(frozen=True)
class CommandIntent:
    command: str
    mode: str | None = None
    mission_file: str | None = None
    session_id: str | None = None
    decision_type: str | None = None
    guard_session_id: str | None = None
    guard_command_id: str | None = None
    reason_parts: tuple[str, ...] = ()
    outcome: str | None = None


def execute(intent: CommandIntent) -> CommandResult:
    if intent.command == "doctor":
        return _doctor()
    if intent.command == "start":
        return _start(intent.mode, intent.mission_file, intent.session_id)
    if intent.command == "status":
        return _status()
    if intent.command == "repair":
        return _repair()
    if intent.command == "next":
        return _next()
    if intent.command == "close":
        return _close(intent.outcome)
    if intent.command == "abandon":
        return _abandon(intent.reason_parts)
    if intent.command == "guard-stop":
        return _guard_stop(intent.guard_session_id, intent.guard_command_id)
    if intent.command == "review":
        return _review()
    if intent.command == "decide":
        return _decide(intent.decision_type)
    raise ValueError(f"unsupported command: {intent.command!r}")


def _start(mode: str | None, mission_file: str | None, session_id: str | None) -> CommandResult:
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
            return CommandResult(
                status="error",
                action="start",
                session_id=state.session_id,
                mode=str(state.mode),
                phase=str(state.phase),
                round=state.round if state.round > 0 else 0,
                missing=_missing_from_blockers(audit.errors),
                blockers=audit.errors,
                next_action="repair RDL session metadata",
            )
        state = existing.state
        blocker = Blocker(
            "active_session_exists",
            str(existing.root / "state.json"),
            "An active RDL session already exists.",
            "Run rdl status, then close or abandon the active session before starting another.",
        )
        return CommandResult(
            status="blocked",
            action="start",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="rdl status",
        )

    try:
        session = store.create_session(mode, mission_path, new_session_id)
    except FileNotFoundError as exc:
        return _template_write_error("start", _synthetic_state(new_session_id, mode), "plan", 1, exc)
    except Exception as exc:
        state = _synthetic_state(new_session_id, mode)
        return _integrity_refresh_error("start", state, "plan", 1, exc)

    state = session.state
    return CommandResult(
        status="ok",
        action="start",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=str(state.phase),
        round=state.round,
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
        return CommandResult(
            status="error",
            action="status",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round if state.round > 0 else 0,
            missing=_missing_from_blockers(state_errors),
            blockers=state_errors,
            next_action="repair RDL session metadata",
        )
    return CommandResult(
        status="ok",
        action="status",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=str(state.phase),
        round=state.round,
        next_action=str(state.status),
    )


def _synthetic_state(session_id: str, mode: str) -> SessionState:
    return SessionState(
        schema_version=1,
        session_id=session_id,
        mode=SessionMode(mode),
        phase=SessionPhase.PLAN,
        round=1,
        status=SessionStatus.ACTIVE,
        mission_file="mission.md",
    )


def _doctor() -> CommandResult:
    loaded = _active_session_result("doctor")
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded

    blockers = tuple(readiness.check(session, "doctor-current"))
    state = session.state
    if blockers:
        return CommandResult(
            status="blocked",
            action="doctor",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(blockers),
            blockers=blockers,
            next_action="complete missing RDL records",
        )

    return CommandResult(
        status="ok",
        action="doctor",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=str(state.phase),
        round=state.round,
        next_action="rdl review",
    )


def _repair() -> CommandResult:
    loaded = _active_session_result("repair", audit=False)
    if isinstance(loaded, CommandResult):
        return loaded
    session = loaded
    state = session.state

    result = repair.repair(session)
    if result.errors:
        return CommandResult(
            status="error",
            action="repair",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(result.errors),
            blockers=result.errors,
            next_action="restore unsafe files before repair",
        )
    if result.blockers:
        next_action = (
            "retry after lock clears"
            if any(blocker.code in {"session_locked", "stale_lock"} for blocker in result.blockers)
            else "restore unsafe files before repair"
        )
        return CommandResult(
            status="blocked",
            action="repair",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(result.blockers),
            blockers=result.blockers,
            next_action=next_action,
        )

    repaired_session = SessionStore.cwd().load_session(session.root)
    audit = repaired_session.audit()
    if audit.errors:
        return CommandResult(
            status="error",
            action="repair",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(audit.errors),
            blockers=audit.errors,
            next_action="inspect repaired session",
        )
    if audit.blockers:
        return CommandResult(
            status="blocked",
            action="repair",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(audit.blockers),
            blockers=audit.blockers,
            next_action="inspect repaired session",
        )

    return CommandResult(
        status="ok",
        action="repair",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=str(state.phase),
        round=state.round,
        next_action=",".join(result.repaired),
    )


def _next() -> CommandResult:
    return _run_locked_session("next", _next_locked)


def _next_locked(session: Session) -> CommandResult:
    state = session.state

    blockers = tuple(readiness.check(session, "advance"))
    if blockers:
        return CommandResult(
            status="blocked",
            action="next",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(blockers),
            blockers=blockers,
            next_action="complete current round review and decision",
        )

    try:
        result = transition.advance(session)
    except transition.TransitionBlocked as exc:
        return CommandResult(
            status="blocked",
            action="next",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers((exc.blocker,)),
            blockers=(exc.blocker,),
            next_action="inspect existing next round",
        )

    try:
        refreshed = SessionStore.cwd().active_session()
        if refreshed is None:
            raise ValueError("active session disappeared after transition")
        integrity.refresh(refreshed)
    except Exception as exc:
        return _integrity_refresh_error("next", state, result.phase, result.round, exc)

    return CommandResult(
        status="ok",
        action="next",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=result.phase,
        round=result.round,
        next_action=result.next_action,
    )


def _review() -> CommandResult:
    return _run_locked_session("review", _review_locked)


def _review_locked(session: Session) -> CommandResult:
    state = session.state
    review_file = session.round_dir() / "review.md"

    if not review_file.is_file():
        try:
            templates.copy_template("review.md", review_file)
        except Exception as exc:
            return _template_write_error("review", state, str(state.phase), state.round, exc)
        try:
            integrity.refresh(SessionStore.cwd().load_session(session.root))
        except Exception as exc:
            return _integrity_refresh_error("review", state, str(state.phase), state.round, exc)
        return CommandResult(
            status="ok",
            action="review",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            next_action=str(review_file),
        )

    blockers = tuple(documents.validate("review", review_file))
    if blockers:
        return CommandResult(
            status="blocked",
            action="review",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(blockers),
            blockers=blockers,
            next_action="complete review.md",
        )

    return CommandResult(
        status="ok",
        action="review",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=str(state.phase),
        round=state.round,
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

    return _run_locked_session("decide", lambda session: _decide_locked(session, decision_type))


def _decide_locked(session: Session, decision_type: str) -> CommandResult:
    state = session.state
    decision_file = session.round_dir() / "decision.md"
    expected_closes = descriptor.expected_closes(state.mode)

    if not decision_file.is_file():
        try:
            templates.write_decision(decision_file, decision_type, expected_closes)
        except Exception as exc:
            return _template_write_error("decide", state, str(state.phase), state.round, exc)
        try:
            integrity.refresh(SessionStore.cwd().load_session(session.root))
        except Exception as exc:
            return _integrity_refresh_error("decide", state, str(state.phase), state.round, exc)
        return CommandResult(
            status="ok",
            action="decide",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
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
        return CommandResult(
            status="blocked",
            action="decide",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(blockers),
            blockers=tuple(blockers),
            next_action="complete decision.md",
        )

    return CommandResult(
        status="ok",
        action="decide",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=str(state.phase),
        round=state.round,
        next_action="rdl next",
    )


def _close(outcome: str | None) -> CommandResult:
    if not outcome:
        blocker = Blocker(
            "missing_close_outcome",
            "",
            "close requires positive, negative, or inconclusive.",
            "rdl close positive",
        )
        return CommandResult(
            status="error",
            action="close",
            missing=_missing_from_blockers((blocker,)),
            blockers=(blocker,),
            next_action="rdl close positive",
        )
    if not descriptor.value_allowed("close-outcome", outcome):
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

    return _run_locked_session("close", lambda session: _close_locked(session, outcome))


def _close_locked(session: Session, outcome: str) -> CommandResult:
    state = session.state
    blockers = list(readiness.check(session, "advance"))
    blockers.extend(readiness.check(session, "close", outcome=outcome))

    decision_file = session.round_dir() / "decision.md"
    expected_decision = f"close-{outcome}"
    if decision_file.is_file() and documents.field(decision_file, "Decision") != expected_decision:
        blockers.append(
            Blocker(
                "invalid_close_decision",
                f"{decision_file}#Decision",
                f"Close outcome requires Decision: {expected_decision}.",
                f"Run rdl decide {expected_decision} or update decision.md.",
            )
        )

    if blockers:
        return CommandResult(
            status="blocked",
            action="close",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(blockers),
            blockers=tuple(blockers),
            next_action="complete close records",
        )

    result = transition.close(session, outcome)
    try:
        integrity.refresh(SessionStore.cwd().load_session(session.root))
    except Exception as exc:
        return _integrity_refresh_error("close", state, result.phase, result.round, exc)

    return CommandResult(
        status="ok",
        action="close",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=result.phase,
        round=result.round,
        next_action=result.next_action,
    )


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

    return _run_locked_session("abandon", lambda session: _abandon_locked(session, reason))


def _abandon_locked(session: Session, reason: str) -> CommandResult:
    state = session.state

    result = transition.abandon(session, reason)
    try:
        integrity.refresh(SessionStore.cwd().load_session(session.root))
    except Exception as exc:
        return _integrity_refresh_error("abandon", state, result.phase, result.round, exc)

    return CommandResult(
        status="ok",
        action="abandon",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=result.phase,
        round=result.round,
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
        return CommandResult(
            status="ok",
            action="guard-stop",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            next_action="allow",
        )
    if guard_command_id and guard_command_id == state.last_guard_command_id:
        return CommandResult(
            status="ok",
            action="guard-stop",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            next_action="allow",
        )

    return _run_locked_session(
        "guard-stop",
        lambda locked_session: _guard_stop_locked(locked_session, guard_session_id, guard_command_id),
        session=session,
        audit=False,
    )


def _guard_stop_locked(session: Session, guard_session_id: str | None, guard_command_id: str | None) -> CommandResult:
    state = session.state

    audit = session.audit()
    if audit.errors:
        return CommandResult(
            status="error",
            action="guard-stop",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round if state.round > 0 else 0,
            missing=_missing_from_blockers(audit.errors),
            blockers=audit.errors,
            next_action="block",
        )
    if audit.blockers:
        return CommandResult(
            status="blocked",
            action="guard-stop",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(audit.blockers),
            blockers=audit.blockers,
            next_action="block",
        )

    blockers = _guard_stop_readiness(session)
    if blockers:
        return CommandResult(
            status="blocked",
            action="guard-stop",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(blockers),
            blockers=tuple(blockers),
            next_action="block",
        )

    try:
        result = transition.from_decision(session)
    except transition.TransitionBlocked as exc:
        return CommandResult(
            status="blocked",
            action="guard-stop",
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers((exc.blocker,)),
            blockers=(exc.blocker,),
            next_action="block",
        )

    if (guard_session_id and guard_session_id != state.guard_session_id) or (guard_command_id and guard_command_id != state.last_guard_command_id):
        transition.mark_guard_seen(SessionStore.cwd().load_session(session.root), guard_session_id, guard_command_id)

    try:
        integrity.refresh(SessionStore.cwd().load_session(session.root))
    except Exception as exc:
        return _integrity_refresh_error("guard-stop", state, result.phase, result.round, exc)

    return CommandResult(
        status="ok",
        action="guard-stop",
        session_id=state.session_id,
        mode=str(state.mode),
        phase=result.phase,
        round=result.round,
        next_action=result.next_action,
    )


def _guard_stop_readiness(session) -> list[Blocker]:
    blockers = list(readiness.check(session, "guard-stop-advance"))
    decision = documents.field(session.round_dir() / "decision.md", "Decision")
    outcome = descriptor.close_outcome_for_decision(decision)
    if outcome:
        blockers.extend(readiness.check(session, "guard-stop-close", outcome=outcome))
    return blockers


def _run_locked_session(
    action: str,
    body: Callable[[Session], CommandResult],
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
            if audit:
                audit_result = locked_session.audit()
                state = locked_session.state
                if audit_result.errors:
                    return CommandResult(
                        status="error",
                        action=action,
                        session_id=state.session_id,
                        mode=str(state.mode),
                        phase=str(state.phase),
                        round=state.round if state.round > 0 else 0,
                        missing=_missing_from_blockers(audit_result.errors),
                        blockers=audit_result.errors,
                        next_action="repair RDL session metadata",
                    )
                if audit_result.blockers:
                    return CommandResult(
                        status="blocked",
                        action=action,
                        session_id=state.session_id,
                        mode=str(state.mode),
                        phase=str(state.phase),
                        round=state.round,
                        missing=_missing_from_blockers(audit_result.blockers),
                        blockers=audit_result.blockers,
                        next_action="complete missing RDL records",
                    )
            return body(locked_session)
    except SessionLockError as exc:
        return CommandResult(
            status="blocked",
            action=action,
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round if state.round > 0 else 0,
            missing=_missing_from_blockers((exc.blocker,)),
            blockers=(exc.blocker,),
            next_action="retry after lock clears",
        )


def _active_session_result(action: str, audit: bool = True):
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
        return CommandResult(
            status="error",
            action=action,
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round if state.round > 0 else 0,
            missing=_missing_from_blockers(audit.errors),
            blockers=audit.errors,
            next_action="repair RDL session metadata",
        )
    if audit.blockers:
        return CommandResult(
            status="blocked",
            action=action,
            session_id=state.session_id,
            mode=str(state.mode),
            phase=str(state.phase),
            round=state.round,
            missing=_missing_from_blockers(audit.blockers),
            blockers=audit.blockers,
            next_action="complete missing RDL records",
        )

    return session


def _integrity_refresh_error(action: str, state, phase: str, round_number: int, exc: Exception) -> CommandResult:
    blocker = Blocker(
        "integrity_refresh_failed",
        "integrity.json",
        f"Integrity refresh failed: {exc}",
        "Inspect the session and run rdl repair when available.",
    )
    return CommandResult(
        status="error",
        action=action,
        session_id=state.session_id,
        mode=str(state.mode),
        phase=phase,
        round=round_number,
        missing=_missing_from_blockers((blocker,)),
        blockers=(blocker,),
        next_action="repair RDL session metadata",
    )


def _template_write_error(action: str, state, phase: str, round_number: int, exc: Exception) -> CommandResult:
    blocker = Blocker(
        "template_write_failed",
        "templates",
        f"Template write failed: {exc}",
        "Inspect RDL templates and retry the command.",
    )
    return CommandResult(
        status="error",
        action=action,
        session_id=state.session_id,
        mode=str(state.mode),
        phase=phase,
        round=round_number,
        missing=_missing_from_blockers((blocker,)),
        blockers=(blocker,),
        next_action="repair RDL templates",
    )


def _missing_from_blockers(blockers: Sequence[Blocker]) -> tuple[str, ...]:
    missing: list[str] = []
    seen: set[str] = set()
    for blocker in blockers:
        path = blocker.file
        if path and path not in seen:
            seen.add(path)
            missing.append(path)
    return tuple(missing)


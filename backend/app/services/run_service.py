"""Business operations for runs and their action timelines."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.action import Action
from app.models.journey import Journey
from app.models.base import utc_now
from app.models.run import Run, RunStatus
from app.schemas.run import ActionCreate


def start_run(session: Session, journey: Journey) -> Run:
    run = Run(journey_id=journey.id)
    run.begin()
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_run(session: Session, run_id: str) -> Run | None:
    return session.get(Run, run_id)


def list_runs(session: Session, journey_id: str) -> list[Run]:
    statement = select(Run).where(Run.journey_id == journey_id).order_by(Run.created_at.desc())
    return list(session.scalars(statement))


def record_action(session: Session, run: Run, payload: ActionCreate) -> Action:
    action = Action(run_id=run.id, **payload.model_dump())
    session.add(action)
    session.commit()
    session.refresh(action)
    return action


def record_system_action(
    session: Session,
    run: Run,
    action_type: str,
    target: str | None,
    outcome: str,
) -> Action:
    """Record a browser-system action without an HTTP request payload."""
    return record_action(session, run, ActionCreate(action_type=action_type, target=target, outcome=outcome))


def mark_failed(session: Session, run: Run, reason: str) -> None:
    """Finish a run when the browser cannot safely continue."""
    run.status = RunStatus.FAILED
    run.completed_at = utc_now()
    record_system_action(session, run, "browser_error", None, reason)
    session.commit()


def mark_awaiting_user(
    session: Session, run: Run, request: str, action_type: str = "user_input_required"
) -> None:
    """Pause for a human-only browser step without treating it as a product failure."""
    run.status = RunStatus.AWAITING_USER
    record_system_action(session, run, action_type, None, request)
    session.commit()


def resume_after_user_input(session: Session, run: Run) -> None:
    """Return a paused run to its active browser loop."""
    run.status = RunStatus.RUNNING
    record_system_action(session, run, "user_input_completed", None, "User completed the required browser-only step.")
    session.commit()


def mark_completed_with_issues(session: Session, run: Run, summary: str) -> None:
    """Finish an audit intentionally after collecting reproducible issues."""
    run.status = RunStatus.COMPLETED_WITH_ISSUES
    run.completed_at = utc_now()
    record_system_action(session, run, "audit_complete", None, summary)
    session.commit()


def mark_stopped(session: Session, run: Run) -> None:
    """End an active audit at the user's request while retaining its evidence."""
    run.status = RunStatus.STOPPED
    run.completed_at = utc_now()
    record_system_action(session, run, "audit_stopped", None, "User stopped this audit. Evidence collected so far was retained.")
    session.commit()


def mark_passed(session: Session, run: Run, summary: str) -> None:
    """Finish a run after the agent observes the requested success state."""
    run.status = RunStatus.PASSED
    run.completed_at = utc_now()
    record_system_action(session, run, "journey_complete", None, summary)
    session.commit()


def list_actions(session: Session, run_id: str) -> list[Action]:
    statement = select(Action).where(Action.run_id == run_id).order_by(Action.created_at.asc())
    return list(session.scalars(statement))

import asyncio
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
from app.models.evidence import EvidenceType
from app.schemas.application import ApplicationCreate, ApplicationUpdate
from app.schemas.journey import JourneyCreate
from app.schemas.run import ActionCreate
from app.services import agent_run_service, application_service, evidence_service, run_service


def make_session() -> Session:
    """Return an isolated in-memory database session for one test."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_application_journey_run_and_action_lifecycle() -> None:
    session = make_session()

    application = application_service.create_application(
        session,
        ApplicationCreate(name="DemoShop", target_url="http://localhost:3001"),
    )
    journey = application_service.create_journey(
        session,
        application,
        JourneyCreate(
            name="Complete checkout",
            goal="Find a laptop, add it to the cart, and complete checkout.",
        ),
    )
    run = run_service.start_run(session, journey)
    run_id = run.id
    action = run_service.record_action(
        session,
        run,
        ActionCreate(action_type="open_url", target="http://localhost:3001"),
    )
    evidence = evidence_service.record_text(
        session,
        run.id,
        EvidenceType.NETWORK_FAILURE,
        "500 http://localhost:3001/api/checkout",
    )

    assert run.status.value == "running"
    assert run.started_at is not None
    assert action.run_id == run.id
    assert evidence.run_id == run.id
    assert [item.action_type for item in run_service.list_actions(session, run.id)] == ["open_url"]
    assert [item.evidence_type for item in evidence_service.list_evidence(session, run.id)] == [
        EvidenceType.NETWORK_FAILURE
    ]


def test_updating_an_application_preserves_its_existing_journeys() -> None:
    """Editing the next test URL must not discard a product's saved work."""
    session = make_session()
    application = application_service.create_application(
        session,
        ApplicationCreate(name="Original product", target_url="http://localhost:3001"),
    )
    application_service.create_journey(
        session,
        application,
        JourneyCreate(name="First visit", goal="Review the first user flow"),
    )

    updated = application_service.update_application(
        session,
        application,
        ApplicationUpdate(
            name="Updated product",
            target_url="https://example.com",
            repository_url=None,
            repository_branch="release",
        ),
    )

    assert updated.name == "Updated product"
    assert updated.target_url == "https://example.com/"
    assert updated.repository_branch == "release"
    journeys = application_service.list_journeys(session, updated.id)
    assert [journey.name for journey in journeys] == ["First visit"]


def test_new_browser_diagnostics_are_recorded_once(monkeypatch) -> None:
    session = make_session()
    application = application_service.create_application(
        session, ApplicationCreate(name="DemoShop", target_url="http://localhost:3001")
    )
    journey = application_service.create_journey(
        session, application, JourneyCreate(name="Checkout", goal="Complete checkout")
    )
    run = run_service.start_run(session, journey)
    run_id = run.id

    class BrowserWithDiagnostics:
        network_failures = ["500 http://localhost:3001/api/checkout"]

    monkeypatch.setattr(agent_run_service, "SessionLocal", lambda: session)
    network_cursor = agent_run_service._record_new_diagnostics(run_id, BrowserWithDiagnostics(), 0)
    agent_run_service._record_new_diagnostics(
        run_id, BrowserWithDiagnostics(), network_cursor
    )

    stored = evidence_service.list_evidence(session, run_id)
    assert [item.evidence_type for item in stored] == [EvidenceType.NETWORK_FAILURE]


def test_ux_feedback_receives_a_dedicated_screenshot(monkeypatch) -> None:
    session = make_session()
    application = application_service.create_application(
        session, ApplicationCreate(name="Feedback test", target_url="http://localhost:3004")
    )
    journey = application_service.create_journey(
        session, application, JourneyCreate(name="Review", goal="Review the first-time-user flow", persona="ux_reviewer")
    )
    run = run_service.start_run(session, journey)
    run_id = run.id

    class BrowserWithScreenshot:
        async def take_feedback_screenshot(self, _: str, __: str) -> Path:
            return Path("/tmp/ux-feedback.png")

    monkeypatch.setattr(agent_run_service, "SessionLocal", lambda: session)
    asyncio.run(
        agent_run_service._capture_feedback_screenshot(
            run_id,
            BrowserWithScreenshot(),
            "The primary action has no visible label.",
        )
    )

    screenshot = evidence_service.list_evidence(session, run_id)[0]
    assert screenshot.evidence_type == EvidenceType.SCREENSHOT
    assert screenshot.content == "UX feedback: The primary action has no visible label."
    assert screenshot.file_path == "/tmp/ux-feedback.png"


def test_authentication_handoff_pauses_without_failing_the_run() -> None:
    session = make_session()
    application = application_service.create_application(
        session, ApplicationCreate(name="Protected app", target_url="http://localhost:3002")
    )
    journey = application_service.create_journey(
        session, application, JourneyCreate(name="Sign in", goal="Open the account page")
    )
    run = run_service.start_run(session, journey)

    run_service.mark_awaiting_user(session, run, "Complete sign-in in the browser window.")

    assert run.status.value == "awaiting_user"
    assert run.completed_at is None
    assert run_service.list_actions(session, run.id)[-1].action_type == "user_input_required"

    run_service.resume_after_user_input(session, run)

    assert run.status.value == "running"
    assert run_service.list_actions(session, run.id)[-1].action_type == "user_input_completed"

    run_service.mark_completed_with_issues(session, run, "Audit finished after two captured issues.")

    assert run.status.value == "completed_with_issues"
    assert run.completed_at is not None
    assert run_service.list_actions(session, run.id)[-1].action_type == "audit_complete"


def test_user_can_stop_an_active_audit_without_losing_its_evidence() -> None:
    session = make_session()
    application = application_service.create_application(
        session, ApplicationCreate(name="Stop test", target_url="http://localhost:3003")
    )
    journey = application_service.create_journey(
        session, application, JourneyCreate(name="Audit", goal="Explore the product")
    )
    run = run_service.start_run(session, journey)
    evidence_service.record_text(session, run.id, EvidenceType.BROWSER_ERROR, "Captured before stop")

    run_service.mark_stopped(session, run)

    assert run.status.value == "stopped"
    assert run.completed_at is not None
    assert evidence_service.list_evidence(session, run.id)[0].content == "Captured before stop"
    assert run_service.list_actions(session, run.id)[-1].action_type == "audit_stopped"


def test_ux_review_finishes_cleanly_when_no_findings_are_reported(monkeypatch) -> None:
    """An exploratory review should not ask for guidance merely because it is done."""
    session = make_session()
    application = application_service.create_application(
        session, ApplicationCreate(name="Clean review", target_url="http://localhost:3005")
    )
    journey = application_service.create_journey(
        session,
        application,
        JourneyCreate(name="UX review", goal="Review the landing page", persona="ux_reviewer"),
    )
    run = run_service.start_run(session, journey)
    run_id = run.id

    monkeypatch.setattr(agent_run_service, "SessionLocal", lambda: session)
    agent_run_service._finish_ux_review(run_id, set(), "No additional safe review action was available.")

    refreshed_run = run_service.get_run(session, run_id)
    assert refreshed_run is not None
    assert refreshed_run.status.value == "passed"
    assert run_service.list_actions(session, run_id)[-1].action_type == "journey_complete"


def test_ux_review_keeps_findings_when_it_finishes_automatically(monkeypatch) -> None:
    """A completed UX review must retain its issue outcome instead of being marked clean."""
    session = make_session()
    application = application_service.create_application(
        session, ApplicationCreate(name="Issue review", target_url="http://localhost:3006")
    )
    journey = application_service.create_journey(
        session,
        application,
        JourneyCreate(name="UX review", goal="Review the landing page", persona="ux_reviewer"),
    )
    run = run_service.start_run(session, journey)
    run_id = run.id

    monkeypatch.setattr(agent_run_service, "SessionLocal", lambda: session)
    agent_run_service._finish_ux_review(
        run_id,
        {"ux:Primary action lacks a visible label."},
        "No additional safe review action was available.",
    )

    refreshed_run = run_service.get_run(session, run_id)
    assert refreshed_run is not None
    assert refreshed_run.status.value == "completed_with_issues"
    assert run_service.list_actions(session, run_id)[-1].action_type == "audit_complete"

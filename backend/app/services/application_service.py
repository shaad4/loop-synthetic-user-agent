"""Business operations for applications and journeys."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.journey import Journey
from app.schemas.application import ApplicationCreate, ApplicationUpdate
from app.schemas.journey import JourneyCreate


def create_application(session: Session, payload: ApplicationCreate) -> Application:
    application = Application(
        name=payload.name,
        target_url=str(payload.target_url),
        repository_url=str(payload.repository_url) if payload.repository_url else None,
        repository_branch=payload.repository_branch,
    )
    session.add(application)
    session.commit()
    session.refresh(application)
    return application


def list_applications(session: Session) -> list[Application]:
    return list(session.scalars(select(Application).order_by(Application.created_at.desc())))


def get_application(session: Session, application_id: str) -> Application | None:
    return session.get(Application, application_id)


def update_application(
    session: Session, application: Application, payload: ApplicationUpdate
) -> Application:
    """Update a test target without changing its journeys or stored run evidence."""
    application.name = payload.name
    application.target_url = str(payload.target_url)
    application.repository_url = str(payload.repository_url) if payload.repository_url else None
    application.repository_branch = payload.repository_branch
    session.commit()
    session.refresh(application)
    return application


def create_journey(session: Session, application: Application, payload: JourneyCreate) -> Journey:
    journey = Journey(application_id=application.id, **payload.model_dump())
    session.add(journey)
    session.commit()
    session.refresh(journey)
    return journey


def list_journeys(session: Session, application_id: str) -> list[Journey]:
    statement = select(Journey).where(Journey.application_id == application_id).order_by(Journey.created_at.desc())
    return list(session.scalars(statement))


def get_journey(session: Session, journey_id: str) -> Journey | None:
    return session.get(Journey, journey_id)

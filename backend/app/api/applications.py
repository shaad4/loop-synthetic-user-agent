"""HTTP endpoints for target applications."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_database_session
from app.schemas.application import ApplicationCreate, ApplicationRead, ApplicationUpdate
from app.schemas.journey import JourneyCreate, JourneyRead
from app.services import application_service

router = APIRouter()


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
def create_application(payload: ApplicationCreate, session: Session = Depends(get_database_session)) -> ApplicationRead:
    try:
        return application_service.create_application(session, payload)
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="An application with this name already exists.") from error


@router.get("", response_model=list[ApplicationRead])
def list_applications(session: Session = Depends(get_database_session)) -> list[ApplicationRead]:
    return application_service.list_applications(session)


@router.get("/{application_id}", response_model=ApplicationRead)
def get_application(application_id: str, session: Session = Depends(get_database_session)) -> ApplicationRead:
    application = application_service.get_application(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    return application


@router.put("/{application_id}", response_model=ApplicationRead)
def update_application(
    application_id: str,
    payload: ApplicationUpdate,
    session: Session = Depends(get_database_session),
) -> ApplicationRead:
    application = application_service.get_application(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    try:
        return application_service.update_application(session, application, payload)
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="An application with this name already exists.") from error


@router.post("/{application_id}/journeys", response_model=JourneyRead, status_code=status.HTTP_201_CREATED)
def create_journey(
    application_id: str,
    payload: JourneyCreate,
    session: Session = Depends(get_database_session),
) -> JourneyRead:
    application = application_service.get_application(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    return application_service.create_journey(session, application, payload)


@router.get("/{application_id}/journeys", response_model=list[JourneyRead])
def list_journeys(application_id: str, session: Session = Depends(get_database_session)) -> list[JourneyRead]:
    application = application_service.get_application(session, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found.")
    return application_service.list_journeys(session, application_id)

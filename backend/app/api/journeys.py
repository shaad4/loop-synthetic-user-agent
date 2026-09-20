"""HTTP endpoints for goal-driven journeys."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_database_session
from app.schemas.journey import JourneyRead
from app.schemas.run import RunRead
from app.services import agent_run_service, application_service, run_service

router = APIRouter()


@router.get("/{journey_id}", response_model=JourneyRead)
def get_journey(journey_id: str, session: Session = Depends(get_database_session)) -> JourneyRead:
    journey = application_service.get_journey(session, journey_id)
    if journey is None:
        raise HTTPException(status_code=404, detail="Journey not found.")
    return journey


@router.post("/{journey_id}/runs", response_model=RunRead, status_code=201)
def start_run(
    journey_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_database_session),
) -> RunRead:
    journey = application_service.get_journey(session, journey_id)
    if journey is None:
        raise HTTPException(status_code=404, detail="Journey not found.")
    run = run_service.start_run(session, journey)
    background_tasks.add_task(agent_run_service.execute_agent_run, run.id)
    return run


@router.get("/{journey_id}/runs", response_model=list[RunRead])
def list_runs(journey_id: str, session: Session = Depends(get_database_session)) -> list[RunRead]:
    journey = application_service.get_journey(session, journey_id)
    if journey is None:
        raise HTTPException(status_code=404, detail="Journey not found.")
    return run_service.list_runs(session, journey_id)

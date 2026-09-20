"""HTTP endpoints for runs and action timelines."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_database_session
from app.schemas.evidence import EvidenceRead
from app.models.run import RunStatus
from app.schemas.run import ActionCreate, ActionRead, InterventionResolution, RunRead
from app.services import agent_run_service, evidence_service, run_service
from app.services.user_intervention_service import user_intervention_service

router = APIRouter()


@router.get("/{run_id}", response_model=RunRead)
def get_run(run_id: str, session: Session = Depends(get_database_session)) -> RunRead:
    run = run_service.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@router.post("/{run_id}/execute", response_model=RunRead, status_code=status.HTTP_202_ACCEPTED)
def execute_run(
    run_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_database_session),
) -> RunRead:
    run = run_service.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run.status.value != "running":
        raise HTTPException(status_code=409, detail="Only a running journey can be executed.")
    background_tasks.add_task(agent_run_service.execute_agent_run, run.id)
    return run


@router.post("/{run_id}/resume", response_model=RunRead)
async def resume_run(
    run_id: str,
    payload: InterventionResolution,
    session: Session = Depends(get_database_session),
) -> RunRead:
    """Resolve an in-browser handoff or decide whether an audit should continue."""
    run = run_service.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run.status != RunStatus.AWAITING_USER:
        raise HTTPException(status_code=409, detail="This journey is not waiting for user input.")
    if not user_intervention_service.resolve(run.id, payload.resolution, payload.guidance):
        raise HTTPException(
            status_code=409,
            detail="The paused browser session is no longer available. Start a new run instead.",
        )
    if payload.resolution == "continue":
        run_service.resume_after_user_input(session, run)
        if payload.guidance:
            run_service.record_system_action(
                session,
                run,
                "user_guidance_added",
                None,
                "User provided additional guidance for the next agent decision.",
            )
    session.refresh(run)
    return run


@router.post("/{run_id}/stop", response_model=RunRead)
def stop_run(run_id: str, session: Session = Depends(get_database_session)) -> RunRead:
    """Stop an active local audit and retain the evidence captured so far."""
    run = run_service.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run.status not in {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.AWAITING_USER}:
        raise HTTPException(status_code=409, detail="Only an active audit can be stopped.")
    user_intervention_service.stop(run.id)
    run_service.mark_stopped(session, run)
    session.refresh(run)
    return run


@router.post("/{run_id}/actions", response_model=ActionRead, status_code=status.HTTP_201_CREATED)
def record_action(
    run_id: str,
    payload: ActionCreate,
    session: Session = Depends(get_database_session),
) -> ActionRead:
    run = run_service.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run_service.record_action(session, run, payload)


@router.get("/{run_id}/actions", response_model=list[ActionRead])
def list_actions(run_id: str, session: Session = Depends(get_database_session)) -> list[ActionRead]:
    run = run_service.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run_service.list_actions(session, run_id)


@router.get("/{run_id}/evidence", response_model=list[EvidenceRead])
def list_evidence(run_id: str, session: Session = Depends(get_database_session)) -> list[EvidenceRead]:
    run = run_service.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return evidence_service.list_evidence(session, run_id)

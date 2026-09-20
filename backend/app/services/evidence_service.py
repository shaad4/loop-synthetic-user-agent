"""Persistence helpers for technical evidence produced by browser runs."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.evidence import Evidence, EvidenceType


def record_text(session: Session, run_id: str, kind: EvidenceType, content: str) -> Evidence:
    evidence = Evidence(run_id=run_id, evidence_type=kind, content=content)
    session.add(evidence)
    session.commit()
    session.refresh(evidence)
    return evidence


def record_file(
    session: Session,
    run_id: str,
    kind: EvidenceType,
    path: Path,
    content: str | None = None,
) -> Evidence:
    """Store a file and an optional short description of what it proves."""
    evidence = Evidence(run_id=run_id, evidence_type=kind, file_path=str(path), content=content)
    session.add(evidence)
    session.commit()
    session.refresh(evidence)
    return evidence


def list_evidence(session: Session, run_id: str) -> list[Evidence]:
    statement = select(Evidence).where(Evidence.run_id == run_id).order_by(Evidence.created_at.asc())
    return list(session.scalars(statement))

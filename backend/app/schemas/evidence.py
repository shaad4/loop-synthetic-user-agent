"""Response models for run evidence."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.evidence import EvidenceType


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    evidence_type: EvidenceType
    content: str | None
    file_path: str | None
    created_at: datetime

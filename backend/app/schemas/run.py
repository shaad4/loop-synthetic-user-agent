"""Request and response models for journey runs and their timelines."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.run import RunStatus


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    journey_id: str
    status: RunStatus
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class ActionCreate(BaseModel):
    action_type: str = Field(min_length=2, max_length=80, examples=["open_url"])
    target: str | None = Field(default=None, max_length=500)
    outcome: str | None = Field(default=None, max_length=4_000)


class InterventionResolution(BaseModel):
    """The user's safe choice after an authentication or audit checkpoint."""

    resolution: Literal["continue", "finish"]
    guidance: str | None = Field(default=None, min_length=3, max_length=1_200)


class ActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    action_type: str
    target: str | None
    outcome: str | None
    created_at: datetime

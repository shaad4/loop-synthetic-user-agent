"""Request and response models for journeys."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JourneyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    goal: str = Field(min_length=10, max_length=4_000)
    persona: str = Field(default="first_time_user", min_length=2, max_length=80)


class JourneyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    application_id: str
    name: str
    goal: str
    persona: str
    created_at: datetime

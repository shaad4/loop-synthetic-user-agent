"""Request and response models for applications."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ApplicationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120, examples=["DemoShop"])
    target_url: HttpUrl = Field(examples=["http://localhost:3001"])
    repository_url: HttpUrl | None = None
    repository_branch: str = Field(default="main", min_length=1, max_length=120)


class ApplicationUpdate(BaseModel):
    """The editable target details for an existing product."""

    name: str = Field(min_length=2, max_length=120, examples=["DemoShop"])
    target_url: HttpUrl = Field(examples=["http://localhost:3001"])
    repository_url: HttpUrl | None = None
    repository_branch: str = Field(default="main", min_length=1, max_length=120)


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    target_url: str
    repository_url: str | None
    repository_branch: str
    created_at: datetime

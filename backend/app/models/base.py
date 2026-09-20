"""Shared SQLAlchemy base class and model helpers."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    """Return a URL-safe unique identifier for persisted records."""
    return str(uuid4())


def utc_now() -> datetime:
    """Return a timezone-aware timestamp in UTC."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base class for all Loop database models."""


class IdentifiedRecord(Base):
    """Base model for records with an ID and creation timestamp."""

    __abstract__ = True

    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)

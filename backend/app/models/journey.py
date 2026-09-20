"""Database model for a goal-driven user journey."""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import IdentifiedRecord


class Journey(IdentifiedRecord):
    __tablename__ = "journeys"

    application_id: Mapped[str] = mapped_column(ForeignKey("applications.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    goal: Mapped[str] = mapped_column(Text)
    persona: Mapped[str] = mapped_column(String(80), default="first_time_user")

    application: Mapped["Application"] = relationship(back_populates="journeys")
    runs: Mapped[list["Run"]] = relationship(back_populates="journey", cascade="all, delete-orphan")

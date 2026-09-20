"""Database model for an application that Loop can test."""

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import IdentifiedRecord


class Application(IdentifiedRecord):
    __tablename__ = "applications"

    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    target_url: Mapped[str] = mapped_column(String(2048))
    repository_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    repository_branch: Mapped[str] = mapped_column(String(120), default="main")

    journeys: Mapped[list["Journey"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )

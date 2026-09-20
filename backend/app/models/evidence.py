"""Database model for technical evidence captured during a journey run."""

from enum import Enum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import IdentifiedRecord


class EvidenceType(str, Enum):
    SCREENSHOT = "screenshot"
    CONSOLE_ERROR = "console_error"
    NETWORK_FAILURE = "network_failure"
    BROWSER_ERROR = "browser_error"


class Evidence(IdentifiedRecord):
    __tablename__ = "evidence"

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    evidence_type: Mapped[EvidenceType] = mapped_column(String(40))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    run: Mapped["Run"] = relationship(back_populates="evidence_items")

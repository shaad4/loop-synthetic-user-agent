"""Database model for a single execution of a journey."""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import IdentifiedRecord, utc_now


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_USER = "awaiting_user"
    COMPLETED_WITH_ISSUES = "completed_with_issues"
    STOPPED = "stopped"
    PASSED = "passed"
    FAILED = "failed"


class Run(IdentifiedRecord):
    __tablename__ = "runs"

    journey_id: Mapped[str] = mapped_column(ForeignKey("journeys.id"), index=True)
    status: Mapped[RunStatus] = mapped_column(SqlEnum(RunStatus), default=RunStatus.QUEUED)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    journey: Mapped["Journey"] = relationship(back_populates="runs")
    actions: Mapped[list["Action"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    evidence_items: Mapped[list["Evidence"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    def begin(self) -> None:
        self.status = RunStatus.RUNNING
        self.started_at = utc_now()

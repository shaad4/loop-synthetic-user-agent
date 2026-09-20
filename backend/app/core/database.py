"""SQLAlchemy engine and request-scoped database sessions."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.base import Base
import app.models  # Ensures every model is registered before tables are created.

engine_options: dict[str, object] = {}
if settings.database_url.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(settings.database_url, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def create_database_tables() -> None:
    """Create local MVP tables when the API starts."""
    Base.metadata.create_all(bind=engine)


def get_database_session() -> Generator[Session, None, None]:
    """Provide one database session per API request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

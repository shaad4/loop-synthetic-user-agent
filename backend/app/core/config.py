"""Configuration values loaded from the local environment."""

from dataclasses import dataclass
from os import getenv
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

BACKEND_DIRECTORY = Path(__file__).resolve().parents[2]


def _storage_directory() -> Path:
    """Resolve the default evidence directory independently of the launch folder."""
    configured_path = Path(getenv("STORAGE_DIRECTORY", "storage"))
    if configured_path.is_absolute():
        return configured_path
    return BACKEND_DIRECTORY / configured_path


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the Loop API."""

    database_url: str
    frontend_url: str
    storage_directory: Path
    openai_api_key: str | None
    agent_model: str
    agent_reasoning_effort: str
    agent_fast_model: str
    agent_fast_reasoning_effort: str
    agent_max_steps: int
    agent_max_reported_issues: int
    agent_max_output_tokens: int
    agent_decision_timeout_seconds: int
    agent_decision_heartbeat_seconds: int
    agent_user_input_timeout_seconds: int
    playwright_headless: bool


settings = Settings(
    database_url=getenv("DATABASE_URL", "sqlite:///./loop.db"),
    frontend_url=getenv("FRONTEND_URL", "http://localhost:3000"),
    storage_directory=_storage_directory(),
    openai_api_key=getenv("OPENAI_API_KEY"),
    agent_model=getenv("LOOP_AGENT_MODEL", "gpt-5.6"),
    agent_reasoning_effort=getenv("LOOP_AGENT_REASONING_EFFORT", "high"),
    agent_fast_model=getenv("LOOP_AGENT_FAST_MODEL", "gpt-5.6-terra"),
    agent_fast_reasoning_effort=getenv("LOOP_AGENT_FAST_REASONING_EFFORT", "medium"),
    agent_max_steps=int(getenv("LOOP_AGENT_MAX_STEPS", "12")),
    agent_max_reported_issues=int(getenv("LOOP_AGENT_MAX_REPORTED_ISSUES", "3")),
    agent_max_output_tokens=int(getenv("LOOP_AGENT_MAX_OUTPUT_TOKENS", "700")),
    agent_decision_timeout_seconds=int(getenv("LOOP_AGENT_DECISION_TIMEOUT_SECONDS", "45")),
    agent_decision_heartbeat_seconds=int(getenv("LOOP_AGENT_DECISION_HEARTBEAT_SECONDS", "6")),
    agent_user_input_timeout_seconds=int(getenv("LOOP_AGENT_USER_INPUT_TIMEOUT_SECONDS", "600")),
    playwright_headless=getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true",
)

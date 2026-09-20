"""Coordinate a short, in-browser handoff from the Synthetic User to a human.

This intentionally stores only an in-memory resume signal. Passwords, OTPs, and
other secrets are entered by the user into the already-open target browser, never
sent to Loop's API or persisted in its database.
"""

import asyncio
from dataclasses import dataclass


@dataclass
class InterventionWaiter:
    event: asyncio.Event
    resolution: str = "continue"
    guidance: str | None = None


@dataclass(frozen=True)
class InterventionResult:
    resolution: str
    guidance: str | None


class UserInterventionService:
    """Own resume signals for local, in-process agent runs."""

    def __init__(self) -> None:
        self._waiters: dict[str, InterventionWaiter] = {}
        self._stopped_run_ids: set[str] = set()

    def begin(self, run_id: str) -> None:
        """Register a run before exposing its paused state to the frontend."""
        self._waiters[run_id] = InterventionWaiter(event=asyncio.Event())

    async def wait_for_resolution(self, run_id: str, timeout_seconds: int) -> InterventionResult | None:
        """Wait for the local user to finish their browser-only step."""
        waiter = self._waiters.get(run_id)
        if waiter is None:
            return None
        try:
            await asyncio.wait_for(waiter.event.wait(), timeout=timeout_seconds)
            return InterventionResult(waiter.resolution, waiter.guidance)
        except TimeoutError:
            return None
        finally:
            self._waiters.pop(run_id, None)

    def resolve(self, run_id: str, resolution: str, guidance: str | None = None) -> bool:
        """Resolve a waiting run. Returns false after restart or timeout."""
        waiter = self._waiters.get(run_id)
        if waiter is None:
            return False
        waiter.resolution = resolution
        waiter.guidance = guidance
        waiter.event.set()
        return True

    def stop(self, run_id: str) -> None:
        """Wake a paused handoff and prevent a running agent from continuing."""
        self._stopped_run_ids.add(run_id)
        waiter = self._waiters.get(run_id)
        if waiter is not None:
            waiter.resolution = "stop"
            waiter.event.set()

    def is_stop_requested(self, run_id: str) -> bool:
        return run_id in self._stopped_run_ids

    def clear(self, run_id: str) -> None:
        self._waiters.pop(run_id, None)
        self._stopped_run_ids.discard(run_id)


user_intervention_service = UserInterventionService()

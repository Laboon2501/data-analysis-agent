"""In-memory structured event store."""

from __future__ import annotations

from schemas.event import AgentEvent


class InMemoryEventStore:
    """Process-local append-only event store."""

    def __init__(self) -> None:
        self._events: list[AgentEvent] = []

    def append_event(self, event: AgentEvent) -> None:
        """Append a deep copy of an event."""

        self._events.append(event.model_copy(deep=True))

    def list_events(
        self, session_id: str | None = None, job_id: str | None = None
    ) -> list[AgentEvent]:
        """List events, optionally filtered by session and job."""

        return [
            event.model_copy(deep=True)
            for event in self._events
            if (session_id is None or event.session_id == session_id)
            and (job_id is None or event.job_id == job_id)
        ]

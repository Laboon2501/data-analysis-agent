"""Worker backend protocol contracts."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from app.workers.job_models import JobRecord
from schemas.agent_state import AgentCommand, AgentState
from schemas.event import AgentEvent


@runtime_checkable
class WorkerBackend(Protocol):
    """Common interface for local and external worker backends."""

    def submit_job(self, state: AgentState) -> JobRecord:
        """Submit a workflow job and return its current record."""

    def get_job(self, job_id: str) -> JobRecord | None:
        """Return a job record by id."""

    def list_events(self, job_id: str) -> list[AgentEvent]:
        """Return recorded events for one job."""

    def stream_events(self, job_id: str) -> Iterator[AgentEvent]:
        """Yield recorded and future events for one job."""

    def approve(self, job_id: str, command: AgentCommand | str) -> JobRecord:
        """Approve or resume a waiting job."""

    def cancel(self, job_id: str) -> JobRecord:
        """Cancel a job when the backend supports cancellation."""


JobRunner = WorkerBackend

"""Tests for shared worker backend contracts and job models."""

from __future__ import annotations

from collections.abc import Iterator

from app.workers import InMemoryJobRunner, JobRecord, JobResult, JobStatus, WorkerBackend
from schemas import AgentState
from schemas.event import AgentEvent


class MinimalBackend:
    """Small structural implementation used to verify the Protocol contract."""

    def submit_job(self, state: AgentState) -> JobRecord:
        """Return a pending job record."""

        return JobRecord(job_id=state.job_id, session_id=state.session_id, final_state=state)

    def get_job(self, job_id: str) -> JobRecord | None:
        """Return no stored job."""

        return None

    def list_events(self, job_id: str) -> list[AgentEvent]:
        """Return no events."""

        return []

    def stream_events(self, job_id: str) -> Iterator[AgentEvent]:
        """Yield no stream events."""

        return iter(())

    def approve(self, job_id: str, command: str) -> JobRecord:
        """Return a placeholder approved record."""

        return JobRecord(job_id=job_id, session_id="session-1")

    def cancel(self, job_id: str) -> JobRecord:
        """Return a placeholder cancelled record."""

        return JobRecord(job_id=job_id, session_id="session-1", status=JobStatus.CANCELLED)


def test_worker_backend_protocol_is_structural() -> None:
    """WorkerBackend should describe shape without forcing inheritance."""

    assert isinstance(MinimalBackend(), WorkerBackend)
    assert isinstance(InMemoryJobRunner(), WorkerBackend)


def test_job_result_can_be_built_from_record() -> None:
    """JobResult should provide a compact future worker task result model."""

    state = AgentState(session_id="session-1", job_id="job-1", user_message="hello")
    record = JobRecord(
        job_id="job-1",
        session_id="session-1",
        status=JobStatus.COMPLETED,
        final_state=state,
    )

    result = JobResult.from_record(record)

    assert result.job_id == "job-1"
    assert result.session_id == "session-1"
    assert result.status is JobStatus.COMPLETED
    assert result.final_state == state

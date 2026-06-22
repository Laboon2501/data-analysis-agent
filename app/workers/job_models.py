"""Shared job models for worker backend implementations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from schemas._base import StrictBaseModel, utc_now
from schemas.agent_state import AgentCommand, AgentIntent, AgentState


class JobStatus(StrEnum):
    """Lifecycle states shared by local and external worker backends."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobRecord(StrictBaseModel):
    """Stored job metadata and latest state snapshot."""

    job_id: str
    session_id: str
    status: JobStatus = JobStatus.PENDING
    intent: AgentIntent = AgentIntent.UNKNOWN
    command: AgentCommand = AgentCommand.NONE
    final_state: AgentState | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class JobResult(StrictBaseModel):
    """Compact job execution result returned by future worker tasks."""

    job_id: str
    session_id: str
    status: JobStatus
    final_state: AgentState | None = None
    error_message: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)

    @classmethod
    def from_record(cls, record: JobRecord) -> JobResult:
        """Build a result view from a job record."""

        return cls(
            job_id=record.job_id,
            session_id=record.session_id,
            status=record.status,
            final_state=record.final_state,
            error_message=record.error_message,
            updated_at=record.updated_at,
        )


TERMINAL_JOB_STATUSES: frozenset[JobStatus] = frozenset(
    {
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }
)

"""Cancel flag interfaces and in-memory implementation."""

from __future__ import annotations

from typing import Protocol


class CancelPolicy(Protocol):
    """Interface used by node runtime to check whether a job was cancelled."""

    def is_cancelled(self, job_id: str) -> bool:
        """Return whether a job should stop before or between node attempts."""


class InMemoryCancelPolicy:
    """Simple process-local cancel flag store for tests and local development."""

    def __init__(self) -> None:
        self._cancelled_job_ids: set[str] = set()

    def request_cancel(self, job_id: str) -> None:
        """Mark a job as cancelled."""

        self._cancelled_job_ids.add(job_id)

    def clear_cancel(self, job_id: str) -> None:
        """Remove a cancel flag for a job."""

        self._cancelled_job_ids.discard(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        """Return whether a job has a cancel flag."""

        return job_id in self._cancelled_job_ids

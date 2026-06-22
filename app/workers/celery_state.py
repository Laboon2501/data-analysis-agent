"""Shared Celery job state helpers backed by persistence stores."""

from __future__ import annotations

from typing import Any

from app.workers.job_models import JobRecord
from guards.cancel_policy import CancelPolicy
from persistence import CacheStore

JOB_CACHE_PREFIX = "celery_job:"
CANCEL_CACHE_PREFIX = "celery_cancel:"


class StoreCancelPolicy(CancelPolicy):
    """Cancel policy that reads Celery cancel flags from a shared CacheStore."""

    def __init__(self, cache_store: CacheStore) -> None:
        self.cache_store = cache_store

    def is_cancelled(self, job_id: str) -> bool:
        """Return whether a shared cancel flag is set for the job."""

        return bool(self.cache_store.get(cancel_cache_key(job_id)))


def save_job_record(cache_store: CacheStore, job: JobRecord) -> None:
    """Persist the latest JobRecord for API and task processes."""

    cache_store.set(job_cache_key(job.job_id), job)


def load_job_record(cache_store: CacheStore, job_id: str) -> JobRecord | None:
    """Load a JobRecord from the shared cache store."""

    payload = cache_store.get(job_cache_key(job_id))
    if payload is None:
        return None
    if isinstance(payload, JobRecord):
        return payload.model_copy(deep=True)
    if isinstance(payload, dict):
        return JobRecord.model_validate(payload)
    raise TypeError(f"Unsupported Celery job record payload: {type(payload)!r}")


def save_cancel_flag(cache_store: CacheStore, job_id: str) -> None:
    """Persist a cancel flag for a future or running Celery task."""

    cache_store.set(cancel_cache_key(job_id), True)


def clear_cancel_flag(cache_store: CacheStore, job_id: str) -> None:
    """Remove a shared cancel flag when a job is resubmitted."""

    cache_store.delete(cancel_cache_key(job_id))


def job_cache_key(job_id: str) -> str:
    """Return the shared cache key for one job record."""

    return f"{JOB_CACHE_PREFIX}{job_id}"


def cancel_cache_key(job_id: str) -> str:
    """Return the shared cache key for one cancel flag."""

    return f"{CANCEL_CACHE_PREFIX}{job_id}"


def compact_error_payload(exc: BaseException) -> dict[str, Any]:
    """Return a bounded structured error payload for events and job records."""

    return {
        "error_type": exc.__class__.__name__,
        "message": str(exc)[:500],
    }

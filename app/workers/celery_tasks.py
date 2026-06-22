"""Celery tasks that execute existing agent graphs through the local runner."""

from __future__ import annotations

import os
from typing import Any

from app.config import AppConfig
from app.workers.celery_runner import (
    CELERY_TASK_NAME_ENV,
    DEFAULT_CELERY_TASK_NAME,
    CeleryRunnerConfig,
    celery_store_bundle_from_env,
)
from app.workers.celery_state import (
    StoreCancelPolicy,
    compact_error_payload,
    load_job_record,
    save_job_record,
)
from app.workers.datasource_state import load_datasource_registry, save_datasource_registry
from app.workers.job_models import JobRecord, JobResult, JobStatus
from app.workers.job_runner import InMemoryJobRunner
from persistence import (
    ArtifactStore,
    CacheStore,
    CheckpointStore,
    EventStore,
    InMemoryVectorMemoryStore,
)
from schemas._base import utc_now
from schemas.agent_state import AgentState
from schemas.event import AgentEvent, EventType

try:
    from celery import shared_task
except ImportError:  # pragma: no cover - project dependencies include celery.
    shared_task = None  # type: ignore[assignment]

RUN_AGENT_JOB_TASK_NAME = os.getenv(CELERY_TASK_NAME_ENV, DEFAULT_CELERY_TASK_NAME)


class CeleryTaskStoreBundle:
    """Stores used by one Celery task execution."""

    def __init__(
        self,
        *,
        cache_store: CacheStore,
        checkpoint_store: CheckpointStore,
        event_store: EventStore,
        artifact_store: ArtifactStore,
    ) -> None:
        self.cache_store = cache_store
        self.checkpoint_store = checkpoint_store
        self.event_store = event_store
        self.artifact_store = artifact_store


def execute_agent_job(
    payload: dict[str, Any],
    *,
    stores: CeleryTaskStoreBundle | None = None,
) -> dict[str, Any]:
    """Execute one serialized AgentState payload and persist shared job state."""

    state = AgentState.model_validate(payload["state"])
    active_stores = stores or _stores_from_env()
    job = load_job_record(active_stores.cache_store, state.job_id) or JobRecord(
        job_id=state.job_id,
        session_id=state.session_id,
        intent=state.intent,
        command=state.command,
        final_state=state,
    )
    running_job = _save_job_update(
        active_stores.cache_store,
        job,
        status=JobStatus.RUNNING,
        final_state=state,
        error_message=None,
    )
    _append_task_event(
        active_stores.event_store,
        running_job,
        EventType.NODE_START,
        message="Celery task started.",
        payload={"job_id": state.job_id},
    )

    try:
        runner = _build_task_runner(active_stores)
        result_job = runner.submit_job(state)
        if runner.datasource_registry is not None:
            save_datasource_registry(active_stores.cache_store, runner.datasource_registry)
        save_job_record(active_stores.cache_store, result_job)
        return JobResult.from_record(result_job).model_dump(mode="json")
    except Exception as exc:
        active_stores.checkpoint_store.save_checkpoint(state)
        error_payload = compact_error_payload(exc)
        failed_job = _save_job_update(
            active_stores.cache_store,
            running_job,
            status=JobStatus.FAILED,
            final_state=state,
            error_message=error_payload["message"],
        )
        _append_task_event(
            active_stores.event_store,
            failed_job,
            EventType.ERROR,
            message=error_payload["message"],
            payload={"job_id": state.job_id, **error_payload},
        )
        return JobResult.from_record(failed_job).model_dump(mode="json")


if shared_task is not None:

    @shared_task(name=RUN_AGENT_JOB_TASK_NAME)
    def run_agent_job(payload: dict[str, Any]) -> dict[str, Any]:
        """Celery task entrypoint for one agent job."""

        return execute_agent_job(payload)

else:  # pragma: no cover

    def run_agent_job(payload: dict[str, Any]) -> dict[str, Any]:
        """Fallback entrypoint used only when Celery is not installed."""

        return execute_agent_job(payload)


def _stores_from_env() -> CeleryTaskStoreBundle:
    """Build task stores from the same environment as the API runner."""

    config = AppConfig.from_env()
    bundle = celery_store_bundle_from_env(CeleryRunnerConfig.from_app_config(config))
    return CeleryTaskStoreBundle(
        cache_store=bundle.cache_store,
        checkpoint_store=bundle.checkpoint_store,
        event_store=bundle.event_store,
        artifact_store=bundle.artifact_store,
    )


def _build_task_runner(stores: CeleryTaskStoreBundle) -> InMemoryJobRunner:
    """Build a local graph runner that writes through shared task stores."""

    config = AppConfig.from_env()
    datasource_registry = load_datasource_registry(stores.cache_store, config)
    return InMemoryJobRunner(
        datasource_registry=datasource_registry,
        cache_store=stores.cache_store,
        checkpoint_store=stores.checkpoint_store,
        event_store=stores.event_store,
        artifact_store=stores.artifact_store,
        memory_store=InMemoryVectorMemoryStore(),
        cancel_policy=StoreCancelPolicy(stores.cache_store),
    )


def _save_job_update(
    cache_store: CacheStore,
    job: JobRecord,
    **updates: object,
) -> JobRecord:
    """Update and persist one shared JobRecord."""

    updated_job = job.model_copy(update={**updates, "updated_at": utc_now()}, deep=True)
    save_job_record(cache_store, updated_job)
    return updated_job


def _append_task_event(
    event_store: EventStore,
    job: JobRecord,
    event_type: EventType,
    *,
    message: str,
    payload: dict[str, Any],
) -> None:
    """Append a bounded Celery task event to the shared event store."""

    event_store.append_event(
        AgentEvent(
            event_type=event_type,
            session_id=job.session_id,
            job_id=job.job_id,
            node_name="celery_task",
            message=message,
            payload=payload,
        )
    )


__all__ = [
    "CeleryTaskStoreBundle",
    "RUN_AGENT_JOB_TASK_NAME",
    "execute_agent_job",
    "run_agent_job",
]

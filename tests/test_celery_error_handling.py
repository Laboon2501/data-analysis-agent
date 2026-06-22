"""Celery task and submitter error handling tests."""

from __future__ import annotations

import pytest

from app.config import AppConfig
from app.workers import CeleryRunnerConfig, CeleryWorkerBackend
from app.workers.celery_state import load_job_record
from app.workers.celery_tasks import CeleryTaskStoreBundle, execute_agent_job
from app.workers.job_models import JobStatus
from persistence import (
    InMemoryArtifactStore,
    InMemoryCacheStore,
    InMemoryCheckpointStore,
    InMemoryEventStore,
)
from schemas import AgentCommand, AgentIntent, AgentState
from schemas.event import EventType


def test_celery_task_records_structured_error_when_runner_fails(monkeypatch) -> None:
    """Task errors should be persisted as failed job status plus error event."""

    class FailingRunner:
        def submit_job(self, state: AgentState):
            raise RuntimeError(f"boom for {state.job_id}")

    monkeypatch.setattr(
        "app.workers.celery_tasks._build_task_runner",
        lambda stores: FailingRunner(),
    )
    cache_store = InMemoryCacheStore()
    checkpoint_store = InMemoryCheckpointStore()
    event_store = InMemoryEventStore()
    stores = CeleryTaskStoreBundle(
        cache_store=cache_store,
        checkpoint_store=checkpoint_store,
        event_store=event_store,
        artifact_store=InMemoryArtifactStore(),
    )
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="What is revenue?",
        intent=AgentIntent.DIRECT_ANALYSIS,
        command=AgentCommand.ANALYZE,
    )

    result = execute_agent_job({"state": state.model_dump(mode="json")}, stores=stores)

    saved_job = load_job_record(cache_store, "job-1")
    error_event = event_store.list_events(job_id="job-1")[-1]

    assert result["status"] == JobStatus.FAILED.value
    assert saved_job is not None
    assert saved_job.status is JobStatus.FAILED
    assert saved_job.error_message == "boom for job-1"
    assert checkpoint_store.load_checkpoint("session-1", "job-1") is not None
    assert error_event.event_type is EventType.ERROR
    assert error_event.payload["error_type"] == "RuntimeError"
    assert error_event.payload["message"] == "boom for job-1"


def test_celery_runner_records_submitter_error() -> None:
    """Submit failures should update shared job state and emit an error event."""

    def failing_submitter(config: CeleryRunnerConfig, payload: dict) -> str:
        _ = config, payload
        raise RuntimeError("broker unavailable")

    runner = CeleryWorkerBackend(
        app_config=AppConfig(),
        config=CeleryRunnerConfig(broker_url="memory://"),
        task_submitter=failing_submitter,
    )

    with pytest.raises(RuntimeError, match="broker unavailable"):
        runner.submit_job(
            AgentState(
                session_id="session-1",
                job_id="job-1",
                user_message="What is revenue?",
                intent=AgentIntent.DIRECT_ANALYSIS,
                command=AgentCommand.ANALYZE,
            )
        )

    job = runner.get_job("job-1")
    events = runner.list_events("job-1")

    assert job is not None
    assert job.status is JobStatus.FAILED
    assert events[-1].event_type is EventType.ERROR
    assert events[-1].payload["error_type"] == "RuntimeError"

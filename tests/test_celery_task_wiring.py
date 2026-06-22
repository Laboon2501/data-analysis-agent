"""Celery app factory and task execution wiring tests."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from app.workers.celery_app import create_celery_app
from app.workers.celery_runner import CeleryRunnerConfig
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


def test_create_celery_app_uses_config_without_hardcoded_broker(monkeypatch) -> None:
    """Celery app factory should honor injected broker/backend values."""

    class FakeConf(dict):
        def update(self, *args, **kwargs) -> None:
            super().update(*args, **kwargs)

        def __getattr__(self, name: str):
            return self[name]

    class FakeCelery:
        def __init__(self, name: str, *, broker: str, backend: str, include: list[str]) -> None:
            self.name = name
            self.conf = FakeConf(
                broker_url=broker,
                result_backend=backend,
                include=include,
            )

    monkeypatch.setitem(sys.modules, "celery", SimpleNamespace(Celery=FakeCelery))
    app = create_celery_app(
        CeleryRunnerConfig(
            broker_url="memory://",
            result_backend="cache+memory://",
            queue_name="analysis",
            task_name="custom.run_agent_job",
        )
    )

    assert app.conf.broker_url == "memory://"
    assert app.conf.result_backend == "cache+memory://"
    assert app.conf.task_default_queue == "analysis"
    assert "app.workers.celery_tasks" in app.conf.include


def test_execute_agent_job_runs_graph_and_persists_status_events_checkpoint() -> None:
    """Task execution should reuse graph runner and write shared stores."""

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
        user_message="Show monthly GMV trend",
        intent=AgentIntent.DIRECT_ANALYSIS,
        command=AgentCommand.ANALYZE,
    )

    result = execute_agent_job({"state": state.model_dump(mode="json")}, stores=stores)

    saved_job = load_job_record(cache_store, "job-1")
    events = event_store.list_events(job_id="job-1")
    checkpoint = checkpoint_store.load_checkpoint("session-1", "job-1")

    assert result["status"] == JobStatus.COMPLETED.value
    assert saved_job is not None
    assert saved_job.status is JobStatus.COMPLETED
    assert saved_job.final_state is not None
    assert saved_job.final_state.analysis_package is not None
    assert checkpoint is not None
    assert checkpoint.analysis_package is not None
    assert any(event.event_type is EventType.NODE_START for event in events)
    assert any(event.event_type is EventType.DONE for event in events)

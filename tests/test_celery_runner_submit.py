"""Celery runner submission tests with mocked Celery."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppConfig
from app.workers.celery_runner import CeleryRunnerConfig, CeleryWorkerBackend
from app.workers.celery_state import load_job_record
from app.workers.job_models import JobStatus
from persistence import InMemoryArtifactStore, InMemoryCheckpointStore
from schemas import AgentCommand, AgentIntent, AgentState
from schemas.event import AgentEvent, EventType


def test_celery_runner_submit_uses_mocked_celery_app(monkeypatch) -> None:
    """Real submission path should call Celery send_task without starting a worker."""

    sent_tasks = []

    class FakeAsyncResult:
        id = "async-task-1"

    class FakeCeleryApp:
        def send_task(self, task_name: str, *, args: list[dict], queue: str) -> FakeAsyncResult:
            sent_tasks.append({"task_name": task_name, "args": args, "queue": queue})
            return FakeAsyncResult()

    def fake_create_celery_app(config: CeleryRunnerConfig) -> FakeCeleryApp:
        assert config.broker_url == "redis://broker/0"
        return FakeCeleryApp()

    monkeypatch.setattr("app.workers.celery_app.create_celery_app", fake_create_celery_app)
    cache_store = FakeCacheStore()
    event_store = FakeEventStore()
    runner = CeleryWorkerBackend(
        config=CeleryRunnerConfig(
            broker_url="redis://broker/0",
            queue_name="analysis",
            task_name="app.workers.celery_tasks.run_agent_job",
        ),
        cache_store=cache_store,
        checkpoint_store=InMemoryCheckpointStore(),
        event_store=event_store,
        artifact_store=InMemoryArtifactStore(),
    )

    job = runner.submit_job(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="What is revenue?",
            intent=AgentIntent.DIRECT_ANALYSIS,
            command=AgentCommand.ANALYZE,
        )
    )

    saved_job = load_job_record(cache_store, "job-1")
    events = event_store.list_events(job_id="job-1")

    assert job.status is JobStatus.PENDING
    assert saved_job is not None
    assert saved_job.status is JobStatus.PENDING
    assert sent_tasks[0]["task_name"] == "app.workers.celery_tasks.run_agent_job"
    assert sent_tasks[0]["queue"] == "analysis"
    assert sent_tasks[0]["args"][0]["job_id"] == "job-1"
    assert events[0].event_type is EventType.NODE_START
    assert events[0].payload["external_task_id"] == "async-task-1"


def test_celery_runner_without_broker_fails_loudly() -> None:
    """Missing Celery broker config should not silently leave jobs pending."""

    runner = CeleryWorkerBackend(app_config=AppConfig(), config=CeleryRunnerConfig())

    with pytest.raises(RuntimeError, match="DATA_ANALYSIS_AGENT_CELERY_BROKER_URL"):
        runner.submit_job(
            AgentState(
                session_id="session-1",
                job_id="job-1",
                user_message="What is revenue?",
                intent=AgentIntent.DIRECT_ANALYSIS,
                command=AgentCommand.ANALYZE,
            )
        )

    assert runner.get_job("job-1").status is JobStatus.FAILED
    assert runner.list_events("job-1")[-1].event_type is EventType.ERROR


def test_celery_runner_shares_file_datasource_registry_and_session_selection(
    tmp_path: Path,
) -> None:
    """API and worker-style Celery runners should share file datasource state."""

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_month,gmv\n2026-01,100\n", encoding="utf-8")
    cache_store = FakeCacheStore()
    app_config = AppConfig(
        upload_dir=str(tmp_path / "uploads"),
        allow_local_file_paths=True,
    )
    runner = CeleryWorkerBackend(
        app_config=app_config,
        cache_store=cache_store,
        checkpoint_store=InMemoryCheckpointStore(),
        event_store=FakeEventStore(),
        artifact_store=InMemoryArtifactStore(),
        task_submitter=lambda _config, _payload: "task-file-1",
    )

    record = runner.register_file_datasource_from_path(
        datasource_id="orders-file",
        name="Orders file",
        file_path=str(csv_path),
        table_name="orders",
    )
    reloaded_runner = CeleryWorkerBackend(
        app_config=app_config,
        cache_store=cache_store,
        checkpoint_store=InMemoryCheckpointStore(),
        event_store=FakeEventStore(),
        artifact_store=InMemoryArtifactStore(),
        task_submitter=lambda _config, _payload: "task-file-2",
    )
    reloaded_runner.set_session_datasource("session-1", "orders-file")

    job = reloaded_runner.submit_job(
        AgentState(
            session_id="session-1",
            job_id="job-file-1",
            user_message="Show monthly GMV trend",
            intent=AgentIntent.DIRECT_ANALYSIS,
            command=AgentCommand.ANALYZE,
        )
    )

    assert record.original_filename == "orders.csv"
    assert reloaded_runner.get_datasource("orders-file") is not None
    assert job.final_state is not None
    assert job.final_state.datasource_id == "orders-file"
    assert load_job_record(cache_store, "job-file-1").final_state.datasource_id == "orders-file"


class FakeCacheStore:
    """Non-memory CacheStore fake used to exercise the real Celery submit branch."""

    def __init__(self) -> None:
        self.values = {}

    def set(self, key: str, value, ttl_seconds: float | None = None) -> None:
        """Store one value."""

        _ = ttl_seconds
        self.values[key] = value

    def get(self, key: str):
        """Return one stored value."""

        return self.values.get(key)

    def delete(self, key: str) -> None:
        """Delete one value."""

        self.values.pop(key, None)


class FakeEventStore:
    """Non-memory EventStore fake used to avoid external services."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def append_event(self, event: AgentEvent) -> None:
        """Append one event."""

        self.events.append(event)

    def list_events(
        self, session_id: str | None = None, job_id: str | None = None
    ) -> list[AgentEvent]:
        """Return filtered events."""

        return [
            event
            for event in self.events
            if (session_id is None or event.session_id == session_id)
            and (job_id is None or event.job_id == job_id)
        ]

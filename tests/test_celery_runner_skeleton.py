"""Tests for Celery backend compatibility paths without a real broker."""

from __future__ import annotations

from app.config import AppConfig
from app.workers import CeleryRunnerConfig, CeleryWorkerBackend, JobStatus, WorkerBackend
from schemas import AgentCommand, AgentIntent, AgentState
from schemas.event import EventType


def test_celery_config_reads_environment(monkeypatch) -> None:
    """Celery configuration should come from environment variables."""

    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CELERY_BROKER_URL", "redis://broker/1")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CELERY_RESULT_BACKEND", "redis://backend/2")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CELERY_QUEUE", "analysis-jobs")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CELERY_TASK_NAME", "custom.run_job")

    config = CeleryRunnerConfig.from_env()

    assert config.broker_url == "redis://broker/1"
    assert config.result_backend == "redis://backend/2"
    assert config.queue_name == "analysis-jobs"
    assert config.task_name == "custom.run_job"


def test_celery_backend_submit_job_uses_injected_placeholder() -> None:
    """Celery backend should still support injected fake task submission."""

    submitted_payloads = []

    def fake_submitter(config: CeleryRunnerConfig, payload: dict) -> str:
        submitted_payloads.append((config, payload))
        return "celery-task-1"

    runner: WorkerBackend = CeleryWorkerBackend(
        app_config=AppConfig(),
        config=CeleryRunnerConfig(
            broker_url="memory://",
            result_backend=None,
            queue_name="analysis-jobs",
            task_name="custom.run_job",
        ),
        task_submitter=fake_submitter,
    )
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="What is revenue?",
        intent=AgentIntent.DIRECT_ANALYSIS,
        command=AgentCommand.ANALYZE,
    )

    job = runner.submit_job(state)
    events = runner.list_events(job.job_id)

    assert job.status is JobStatus.PENDING
    assert job.final_state is not None
    assert job.final_state.model_dump(exclude={"datasource_id"}) == state.model_dump(
        exclude={"datasource_id"}
    )
    assert job.final_state.datasource_id is not None
    assert submitted_payloads[0][0].task_name == "custom.run_job"
    assert submitted_payloads[0][1]["job_id"] == "job-1"
    assert submitted_payloads[0][1]["state"]["user_message"] == "What is revenue?"
    assert submitted_payloads[0][1]["state"]["datasource_id"] == job.final_state.datasource_id
    assert events[0].event_type is EventType.NODE_START
    assert events[0].payload["submitted"] is True
    assert events[0].payload["external_task_id"] == "celery-task-1"


def test_celery_backend_approve_and_cancel_keep_fake_submitter_compatibility() -> None:
    """Approve and cancel should update shared metadata without a real worker."""

    submitted_payloads = []

    def fake_submitter(config: CeleryRunnerConfig, payload: dict) -> str:
        submitted_payloads.append((config, payload))
        return f"task-{len(submitted_payloads)}"

    runner = CeleryWorkerBackend(
        app_config=AppConfig(),
        config=CeleryRunnerConfig(broker_url="memory://"),
        task_submitter=fake_submitter,
    )
    job = runner.submit_job(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="export report",
            command=AgentCommand.REPORT,
        )
    )

    approved_job = runner.approve(job.job_id, AgentCommand.REPORT_CONFIRM)
    cancelled_job = runner.cancel(job.job_id)
    events = runner.list_events(job.job_id)

    assert approved_job.status is JobStatus.PENDING
    assert approved_job.command is AgentCommand.REPORT_CONFIRM
    assert approved_job.intent is AgentIntent.REPORT_EXPORT
    assert cancelled_job.status is JobStatus.CANCELLED
    assert len(submitted_payloads) == 2
    assert [event.event_type for event in events] == [
        EventType.NODE_START,
        EventType.NODE_START,
        EventType.STOPPED,
    ]

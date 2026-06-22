"""Health endpoint tests for memory and Celery runtime modes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.sessions import SQLAlchemySessionStore
from app.workers import CeleryRunnerConfig, CeleryWorkerBackend, InMemoryJobRunner


def test_health_endpoint_reports_memory_backend(sqlite_data_source) -> None:
    """Memory backend health should be local and ok."""

    client = TestClient(create_app(job_runner=InMemoryJobRunner(data_source=sqlite_data_source)))

    health = client.get("/health").json()
    runtime = client.get("/health/runtime").json()

    assert health == {"status": "ok", "runner_backend": "memory"}
    assert runtime["status"] == "ok"
    assert runtime["runner_backend"] == "memory"
    assert runtime["worker"] == "local"
    assert runtime["data_source_configured"] is True
    assert runtime["upload_dir_configured"] is True
    assert runtime["max_upload_mb"] == 25
    assert runtime["local_file_paths_enabled"] is False
    assert runtime["session_store"]["store_type"] == "memory"
    assert runtime["session_store"]["persistent"] is False


def test_health_endpoint_reports_celery_configuration() -> None:
    """Celery health should check configuration without requiring a live worker."""

    config = AppConfig(artifact_dir="custom-artifacts")
    runner = CeleryWorkerBackend(
        app_config=config,
        config=CeleryRunnerConfig.from_app_config(config),
    )
    client = TestClient(create_app(job_runner=runner))

    health = client.get("/health").json()
    runtime = client.get("/health/runtime").json()

    assert health == {"status": "ok", "runner_backend": "celery"}
    assert runtime["status"] == "degraded"
    assert runtime["runner_backend"] == "celery"
    assert runtime["worker"] == "external"
    assert runtime["broker_configured"] is False
    assert runtime["worker_online_checked"] is False
    assert runtime["artifact_store"] == "FileArtifactStore"
    assert runtime["artifact_dir"] == "custom-artifacts"
    assert runtime["upload_dir_configured"] is True
    assert runtime["max_upload_mb"] == 25
    assert runtime["local_file_paths_enabled"] is False
    assert runtime["session_store"]["store_type"] == "memory"


def test_runtime_health_reports_sqlite_session_store(tmp_path) -> None:
    """Runtime health should expose safe persistent session store metadata."""

    store = SQLAlchemySessionStore(url=f"sqlite:///{tmp_path / 'sessions.sqlite'}")
    client = TestClient(create_app(session_store=store))

    runtime = client.get("/health/runtime").json()

    assert runtime["session_store"]["store_type"] == "sqlite"
    assert runtime["session_store"]["persistent"] is True
    assert "sqlite" in runtime["session_store"]["db_url_masked"]

"""Local integration scripts configuration tests."""

from app.workers import CeleryWorkerBackend, InMemoryJobRunner
from persistence import FileArtifactStore
from scripts.run_api import (
    APISettings,
    build_runner,
    settings_from_env,
)
from scripts.run_api import (
    parse_args as parse_api_args,
)
from scripts.run_api import (
    settings_from_args as api_settings_from_args,
)
from scripts.run_integration_smoke import (
    IntegrationSmokeSettings,
    _multipart_body,
    _parse_sse_text,
    artifact_refs_from_state,
    build_chat_payload,
    celery_diagnostics,
)
from scripts.run_integration_smoke import (
    parse_args as parse_smoke_args,
)
from scripts.run_integration_smoke import (
    settings_from_args as smoke_settings_from_args,
)
from scripts.run_worker import (
    build_worker_command,
    worker_environment_summary,
)
from scripts.run_worker import (
    parse_args as parse_worker_args,
)


def test_run_api_settings_default_to_memory(monkeypatch) -> None:
    """run_api should default to memory backend without external stores."""

    monkeypatch.delenv("DATA_ANALYSIS_AGENT_RUNNER_BACKEND", raising=False)
    settings = settings_from_env()

    assert settings.runner_backend == "memory"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.use_redis_stores is False
    assert settings.use_postgres_checkpoint is False


def test_run_api_settings_parse_cli_and_build_memory_runner() -> None:
    """CLI settings should build an InMemoryJobRunner with demo datasource."""

    args = parse_api_args(["--runner-backend", "memory", "--host", "0.0.0.0", "--port", "9000"])
    settings = api_settings_from_args(args)
    runner = build_runner(settings)

    assert settings.runner_backend == "memory"
    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert isinstance(runner, InMemoryJobRunner)
    assert runner.data_source is not None
    assert runner.data_source.datasource_id == "ecommerce-demo-sqlite"


def test_run_api_builds_celery_runner_without_external_services() -> None:
    """Celery backend construction should not contact Redis or Postgres."""

    runner = build_runner(APISettings(runner_backend="celery"))

    assert isinstance(runner, CeleryWorkerBackend)
    assert runner.config.queue_name == "data-analysis-agent"
    assert isinstance(runner.artifact_store, FileArtifactStore)


def test_run_worker_builds_command_from_cli() -> None:
    """run_worker should construct a clear Celery command without executing it."""

    args = parse_worker_args(
        [
            "--app",
            "project.celery_app",
            "--queue",
            "analysis",
            "--loglevel",
            "DEBUG",
            "--concurrency",
            "2",
        ]
    )

    assert build_worker_command(args) == [
        "celery",
        "-A",
        "project.celery_app",
        "worker",
        "-Q",
        "analysis",
        "--loglevel",
        "DEBUG",
        "--concurrency",
        "2",
    ]


def test_run_worker_environment_summary_reads_celery_env(monkeypatch) -> None:
    """Worker summary should expose Celery env config without starting Celery."""

    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CELERY_BROKER_URL", "redis://broker/0")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CELERY_RESULT_BACKEND", "redis://backend/1")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CELERY_QUEUE", "analysis")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CELERY_TASK_NAME", "custom.run")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CELERY_APP", "project.celery_app")

    summary = worker_environment_summary()

    assert summary == {
        "broker_url": "redis://broker/0",
        "result_backend": "redis://backend/1",
        "redis_url": "redis://broker/0",
        "checkpoint_url": None,
        "artifact_dir": "artifacts",
        "upload_dir": "uploads",
        "max_upload_mb": "25",
        "allow_local_file_paths": "false",
        "datasource_url": None,
        "queue_name": "analysis",
        "task_name": "custom.run",
        "celery_app": "project.celery_app",
    }


def test_run_api_celery_runner_uses_configured_artifact_dir(tmp_path) -> None:
    """API and worker config should point Celery artifacts at the configured directory."""

    settings = APISettings(
        runner_backend="celery",
        app_config=APISettings().app_config.with_overrides(
            runner_backend="celery",
            artifact_dir=str(tmp_path),
        ),
    )

    runner = build_runner(settings)

    assert isinstance(runner, CeleryWorkerBackend)
    assert isinstance(runner.artifact_store, FileArtifactStore)
    assert runner.artifact_store.root_dir == tmp_path.resolve()


def test_integration_smoke_settings_and_payload() -> None:
    """Integration smoke CLI should build a direct analysis chat payload."""

    args = parse_smoke_args(
        [
            "--api-url",
            "http://localhost:9000/",
            "--session-id",
            "session-x",
            "--message",
            "What is total revenue?",
            "--in-process",
            "--sse",
        ]
    )
    settings = smoke_settings_from_args(args)

    assert settings == IntegrationSmokeSettings(
        api_url="http://localhost:9000",
        session_id="session-x",
        message="What is total revenue?",
        runner_backend="memory",
        datasource_kind="sql",
        file_registration_mode="from_path",
        datasource_id=None,
        file_path=None,
        file_table_name=None,
        profile_datasource=False,
        include_exploration=False,
        include_exports=False,
        in_process=True,
        test_sse=True,
    )
    assert build_chat_payload(settings) == {
        "message": "What is total revenue?",
        "command": "none",
    }


def test_integration_smoke_settings_support_file_datasource() -> None:
    """Integration smoke should parse optional file datasource settings."""

    args = parse_smoke_args(
        [
            "--datasource-kind",
            "file",
            "--datasource-id",
            "orders-file",
            "--file-path",
            "orders.csv",
            "--file-table-name",
            "orders",
            "--file-registration-mode",
            "upload",
            "--profile-datasource",
            "--include-exploration",
            "--include-exports",
        ]
    )
    settings = smoke_settings_from_args(args)

    assert settings.datasource_kind == "file"
    assert settings.datasource_id == "orders-file"
    assert settings.file_path == "orders.csv"
    assert settings.file_table_name == "orders"
    assert settings.file_registration_mode == "upload"
    assert settings.profile_datasource is True
    assert settings.include_exploration is True
    assert settings.include_exports is True


def test_integration_smoke_multipart_body_and_celery_diagnostics(tmp_path) -> None:
    """Multipart helper and Celery diagnostics should be local-only and bounded."""

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text("order_month,gmv\n2026-01,100\n", encoding="utf-8")

    body, content_type = _multipart_body(
        {"datasource_id": "orders-file", "table_name": "orders"},
        file_field="file",
        file_path=csv_path,
    )
    diagnostics = celery_diagnostics()

    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="datasource_id"' in body
    assert b'filename="orders.csv"' in body
    assert "docker_cli_found" in diagnostics
    assert "shared DATA_ANALYSIS_AGENT_UPLOAD_DIR" in diagnostics["requires"]


def test_integration_smoke_extracts_artifact_refs_without_content() -> None:
    """Artifact extraction should collect refs without reading artifact bodies."""

    final_state = {
        "chart_spec": {"artifact_ref": "artifact:chart-1"},
        "analysis_package": {"artifact_refs": ["artifact:chart-1", "artifact:file-2"]},
        "report_result": {"artifact_ref": "artifact:report-3"},
    }

    assert artifact_refs_from_state(final_state) == [
        "artifact:chart-1",
        "artifact:file-2",
        "artifact:report-3",
    ]


def test_integration_smoke_parses_sse_frames() -> None:
    """SSE parser should decode finite API stream output."""

    frames = _parse_sse_text(
        'event: node_start\ndata: {"event_type":"node_start"}\n\n'
        'event: done\ndata: {"event_type":"done"}\n\n'
    )

    assert frames == [
        {"event": "node_start", "data": {"event_type": "node_start"}},
        {"event": "done", "data": {"event_type": "done"}},
    ]

"""Central runtime configuration tests."""

from __future__ import annotations

from app.config import AppConfig
from app.workers import CeleryRunnerConfig


def test_app_config_defaults_to_memory_backend(monkeypatch) -> None:
    """Default config should not require external services."""

    for name in (
        "DATA_ANALYSIS_AGENT_RUNNER_BACKEND",
        "DATA_ANALYSIS_AGENT_REDIS_URL",
        "DATA_ANALYSIS_AGENT_CELERY_BROKER_URL",
        "DATA_ANALYSIS_AGENT_DATASOURCE_URL",
        "DATA_ANALYSIS_AGENT_SESSION_STORE",
        "DATA_ANALYSIS_AGENT_SESSION_DB_URL",
        "DATA_ANALYSIS_AGENT_UPLOAD_DIR",
        "DATA_ANALYSIS_AGENT_MAX_UPLOAD_MB",
        "DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS",
    ):
        monkeypatch.delenv(name, raising=False)

    config = AppConfig.from_env()

    assert config.runner_backend == "memory"
    assert config.effective_redis_url is None
    assert config.datasource_url is None
    assert config.artifact_dir == "artifacts"
    assert config.upload_dir == "uploads"
    assert config.max_upload_mb == 25
    assert config.allow_local_file_paths is False
    assert config.session_store == "memory"
    assert config.session_db_url is None


def test_app_config_reads_distributed_runtime_environment(monkeypatch) -> None:
    """Distributed runtime env should map into one typed config object."""

    monkeypatch.setenv("DATA_ANALYSIS_AGENT_RUNNER_BACKEND", "celery")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_REDIS_URL", "redis://redis/0")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CELERY_BROKER_URL", "redis://broker/0")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CELERY_RESULT_BACKEND", "redis://backend/1")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CHECKPOINT_URL", "postgresql://db/checkpoint")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_ARTIFACT_DIR", "runtime-artifacts")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_UPLOAD_DIR", "runtime-uploads")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_MAX_UPLOAD_MB", "12")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS", "true")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_DATASOURCE_URL", "sqlite:///demo.sqlite")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_LLM_MODEL", "gpt-test")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_SESSION_STORE", "sqlite")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_SESSION_DB_URL", "sqlite:///sessions.sqlite")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_SESSION_TTL_DAYS", "30")
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_SESSION_MAX_MESSAGES", "50")

    config = AppConfig.from_env()
    celery_config = CeleryRunnerConfig.from_app_config(config)

    assert config.runner_backend == "celery"
    assert config.effective_redis_url == "redis://redis/0"
    assert config.effective_checkpoint_url == "postgresql://db/checkpoint"
    assert config.artifact_dir == "runtime-artifacts"
    assert config.upload_dir == "runtime-uploads"
    assert config.max_upload_mb == 12
    assert config.allow_local_file_paths is True
    assert config.datasource_url == "sqlite:///demo.sqlite"
    assert config.llm_provider == "openai_compatible"
    assert config.llm_model == "gpt-test"
    assert config.session_store == "sqlite"
    assert config.session_db_url == "sqlite:///sessions.sqlite"
    assert config.session_ttl_days == 30
    assert config.session_max_messages == 50
    assert celery_config.broker_url == "redis://broker/0"
    assert celery_config.result_backend == "redis://backend/1"


def test_app_config_reuses_redis_broker_for_events_when_redis_url_missing(monkeypatch) -> None:
    """Celery Redis broker can be reused for Redis-backed event/cache stores."""

    monkeypatch.delenv("DATA_ANALYSIS_AGENT_REDIS_URL", raising=False)
    monkeypatch.setenv("DATA_ANALYSIS_AGENT_CELERY_BROKER_URL", "redis://broker/0")

    config = AppConfig.from_env()

    assert config.effective_redis_url == "redis://broker/0"

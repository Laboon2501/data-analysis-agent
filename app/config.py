"""Central runtime configuration for local and distributed execution."""

from __future__ import annotations

import os
from typing import Literal

from pydantic import Field

from schemas._base import StrictBaseModel

RUNNER_BACKEND_ENV = "DATA_ANALYSIS_AGENT_RUNNER_BACKEND"
API_HOST_ENV = "DATA_ANALYSIS_AGENT_API_HOST"
API_PORT_ENV = "DATA_ANALYSIS_AGENT_API_PORT"
API_RELOAD_ENV = "DATA_ANALYSIS_AGENT_API_RELOAD"
REDIS_URL_ENV = "DATA_ANALYSIS_AGENT_REDIS_URL"
CELERY_BROKER_URL_ENV = "DATA_ANALYSIS_AGENT_CELERY_BROKER_URL"
CELERY_RESULT_BACKEND_ENV = "DATA_ANALYSIS_AGENT_CELERY_RESULT_BACKEND"
CELERY_QUEUE_ENV = "DATA_ANALYSIS_AGENT_CELERY_QUEUE"
CELERY_TASK_NAME_ENV = "DATA_ANALYSIS_AGENT_CELERY_TASK_NAME"
DATABASE_URL_ENV = "DATA_ANALYSIS_AGENT_DATABASE_URL"
CHECKPOINT_URL_ENV = "DATA_ANALYSIS_AGENT_CHECKPOINT_URL"
POSTGRES_URL_ENV = "DATA_ANALYSIS_AGENT_POSTGRES_URL"
ARTIFACT_DIR_ENV = "DATA_ANALYSIS_AGENT_ARTIFACT_DIR"
UPLOAD_DIR_ENV = "DATA_ANALYSIS_AGENT_UPLOAD_DIR"
MAX_UPLOAD_MB_ENV = "DATA_ANALYSIS_AGENT_MAX_UPLOAD_MB"
ALLOW_LOCAL_FILE_PATHS_ENV = "DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS"
DATASOURCE_URL_ENV = "DATA_ANALYSIS_AGENT_DATASOURCE_URL"
DATASOURCE_ID_ENV = "DATA_ANALYSIS_AGENT_DATASOURCE_ID"
LLM_PROVIDER_ENV = "DATA_ANALYSIS_AGENT_LLM_PROVIDER"
LLM_MODEL_ENV = "DATA_ANALYSIS_AGENT_LLM_MODEL"
LLM_BASE_URL_ENV = "DATA_ANALYSIS_AGENT_LLM_BASE_URL"
LLM_API_KEY_ENV_ENV = "DATA_ANALYSIS_AGENT_LLM_API_KEY_ENV"
LLM_CONFIG_PATH_ENV = "DATA_ANALYSIS_AGENT_LLM_CONFIG_PATH"
LLM_ENABLED_NODES_ENV = "DATA_ANALYSIS_AGENT_LLM_ENABLED_NODES"
SESSION_STORE_ENV = "DATA_ANALYSIS_AGENT_SESSION_STORE"
SESSION_DB_URL_ENV = "DATA_ANALYSIS_AGENT_SESSION_DB_URL"
SESSION_TTL_DAYS_ENV = "DATA_ANALYSIS_AGENT_SESSION_TTL_DAYS"
SESSION_MAX_MESSAGES_ENV = "DATA_ANALYSIS_AGENT_SESSION_MAX_MESSAGES"
RESPONSE_LANGUAGE_ENV = "DATA_ANALYSIS_AGENT_RESPONSE_LANGUAGE"

RunnerBackendName = Literal["memory", "celery"]
SessionStoreName = Literal["memory", "sqlite", "sqlalchemy"]
DEFAULT_CELERY_TASK_NAME = "app.workers.celery_tasks.run_agent_job"
DEFAULT_ARTIFACT_DIR = "artifacts"
DEFAULT_UPLOAD_DIR = "uploads"
DEFAULT_MAX_UPLOAD_MB = 25
DEFAULT_LLM_CONFIG_PATH = "runtime/llm_config.json"


class AppConfig(StrictBaseModel):
    """Environment-backed runtime configuration with safe local defaults."""

    runner_backend: RunnerBackendName = "memory"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_reload: bool = False
    redis_url: str | None = None
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_queue: str = "data-analysis-agent"
    celery_task_name: str = DEFAULT_CELERY_TASK_NAME
    database_url: str | None = None
    checkpoint_url: str | None = None
    artifact_dir: str = DEFAULT_ARTIFACT_DIR
    upload_dir: str = DEFAULT_UPLOAD_DIR
    max_upload_mb: int = DEFAULT_MAX_UPLOAD_MB
    allow_local_file_paths: bool = False
    datasource_url: str | None = None
    datasource_id: str = "configured-datasource"
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_api_key_env: str | None = None
    llm_config_path: str = DEFAULT_LLM_CONFIG_PATH
    llm_enabled_nodes: list[str] = Field(default_factory=list)
    llm_api_key: str | None = Field(default=None, repr=False, exclude=True)
    session_store: SessionStoreName = "memory"
    session_db_url: str | None = None
    session_ttl_days: int | None = None
    session_max_messages: int | None = None
    response_language: str = "zh-CN"

    @classmethod
    def from_env(cls) -> AppConfig:
        """Build runtime configuration from environment variables."""

        database_url = _optional_env(DATABASE_URL_ENV)
        return cls(
            runner_backend=_runner_backend(os.getenv(RUNNER_BACKEND_ENV, "memory")),
            api_host=os.getenv(API_HOST_ENV, "127.0.0.1"),
            api_port=int(os.getenv(API_PORT_ENV, "8000")),
            api_reload=_env_bool(API_RELOAD_ENV, default=False),
            redis_url=_optional_env(REDIS_URL_ENV) or _optional_env("REDIS_URL"),
            celery_broker_url=_optional_env(CELERY_BROKER_URL_ENV),
            celery_result_backend=_optional_env(CELERY_RESULT_BACKEND_ENV),
            celery_queue=os.getenv(CELERY_QUEUE_ENV, "data-analysis-agent"),
            celery_task_name=os.getenv(CELERY_TASK_NAME_ENV, DEFAULT_CELERY_TASK_NAME),
            database_url=database_url,
            checkpoint_url=(
                _optional_env(CHECKPOINT_URL_ENV)
                or _optional_env(POSTGRES_URL_ENV)
                or _optional_env("POSTGRES_URL")
                or _optional_env("DATABASE_URL")
            ),
            artifact_dir=os.getenv(ARTIFACT_DIR_ENV, DEFAULT_ARTIFACT_DIR),
            upload_dir=os.getenv(UPLOAD_DIR_ENV, DEFAULT_UPLOAD_DIR),
            max_upload_mb=int(os.getenv(MAX_UPLOAD_MB_ENV, str(DEFAULT_MAX_UPLOAD_MB))),
            allow_local_file_paths=_env_bool(ALLOW_LOCAL_FILE_PATHS_ENV, default=False),
            datasource_url=_optional_env(DATASOURCE_URL_ENV) or database_url,
            datasource_id=os.getenv(DATASOURCE_ID_ENV, "configured-datasource"),
            llm_provider=_optional_env(LLM_PROVIDER_ENV),
            llm_model=_optional_env(LLM_MODEL_ENV),
            llm_base_url=_optional_env(LLM_BASE_URL_ENV),
            llm_api_key_env=_optional_env(LLM_API_KEY_ENV_ENV),
            llm_config_path=os.getenv(LLM_CONFIG_PATH_ENV, DEFAULT_LLM_CONFIG_PATH),
            llm_enabled_nodes=_env_csv(LLM_ENABLED_NODES_ENV),
            session_store=_session_store(os.getenv(SESSION_STORE_ENV, "memory")),
            session_db_url=_optional_env(SESSION_DB_URL_ENV),
            session_ttl_days=_optional_int_env(SESSION_TTL_DAYS_ENV),
            session_max_messages=_optional_int_env(SESSION_MAX_MESSAGES_ENV),
            response_language=os.getenv(RESPONSE_LANGUAGE_ENV, "zh-CN"),
        )

    @property
    def effective_redis_url(self) -> str | None:
        """Return explicit Redis URL or reuse a Redis Celery broker URL."""

        if self.redis_url:
            return self.redis_url
        broker_url = self.celery_broker_url or ""
        if broker_url.startswith(("redis://", "rediss://", "unix://")):
            return broker_url
        return None

    @property
    def effective_checkpoint_url(self) -> str | None:
        """Return the checkpoint URL used by PostgresCheckpointStore."""

        return self.checkpoint_url

    def with_overrides(self, **updates: object) -> AppConfig:
        """Return a config copy with CLI overrides applied."""

        clean_updates = {key: value for key, value in updates.items() if value is not None}
        return self.model_copy(update=clean_updates)


def _optional_env(name: str) -> str | None:
    """Return a stripped env value or None for missing/blank values."""

    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _runner_backend(value: str) -> RunnerBackendName:
    """Normalize runner backend names from env or CLI."""

    normalized = value.strip().lower()
    if normalized not in {"memory", "celery"}:
        raise ValueError(f"Unsupported runner backend: {value}")
    return normalized  # type: ignore[return-value]


def _session_store(value: str) -> SessionStoreName:
    """Normalize session store backend names from env."""

    normalized = value.strip().lower()
    if normalized not in {"memory", "sqlite", "sqlalchemy"}:
        raise ValueError(f"Unsupported session store: {value}")
    return normalized  # type: ignore[return-value]


def _env_csv(name: str) -> list[str]:
    """Return comma-separated environment values as a list."""

    raw_value = _optional_env(name)
    if raw_value is None:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _optional_int_env(name: str) -> int | None:
    """Return an int env value or None for missing/blank values."""

    raw_value = _optional_env(name)
    if raw_value is None:
        return None
    return int(raw_value)


def _env_bool(name: str, *, default: bool) -> bool:
    """Parse common true/false environment variable values."""

    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "API_HOST_ENV",
    "API_PORT_ENV",
    "API_RELOAD_ENV",
    "ARTIFACT_DIR_ENV",
    "ALLOW_LOCAL_FILE_PATHS_ENV",
    "AppConfig",
    "CELERY_BROKER_URL_ENV",
    "CELERY_QUEUE_ENV",
    "CELERY_RESULT_BACKEND_ENV",
    "CELERY_TASK_NAME_ENV",
    "CHECKPOINT_URL_ENV",
    "DATABASE_URL_ENV",
    "DATASOURCE_ID_ENV",
    "DATASOURCE_URL_ENV",
    "DEFAULT_ARTIFACT_DIR",
    "DEFAULT_CELERY_TASK_NAME",
    "DEFAULT_MAX_UPLOAD_MB",
    "DEFAULT_LLM_CONFIG_PATH",
    "DEFAULT_UPLOAD_DIR",
    "LLM_API_KEY_ENV_ENV",
    "LLM_CONFIG_PATH_ENV",
    "LLM_ENABLED_NODES_ENV",
    "LLM_BASE_URL_ENV",
    "LLM_MODEL_ENV",
    "LLM_PROVIDER_ENV",
    "POSTGRES_URL_ENV",
    "REDIS_URL_ENV",
    "RUNNER_BACKEND_ENV",
    "RunnerBackendName",
    "SESSION_DB_URL_ENV",
    "SESSION_MAX_MESSAGES_ENV",
    "SESSION_STORE_ENV",
    "SESSION_TTL_DAYS_ENV",
    "SessionStoreName",
    "MAX_UPLOAD_MB_ENV",
    "UPLOAD_DIR_ENV",
]

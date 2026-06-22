"""Local FastAPI runner for manual integration smoke tests."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pydantic import Field

from app.api import create_app
from app.config import (
    RUNNER_BACKEND_ENV,
    SESSION_DB_URL_ENV,
    SESSION_STORE_ENV,
    AppConfig,
    RunnerBackendName,
)
from app.sessions import build_session_store
from app.workers import CeleryRunnerConfig, CeleryWorkerBackend, InMemoryJobRunner, WorkerBackend
from datasource import DataSourceRegistry
from persistence import (
    ArtifactStore,
    CacheStore,
    CheckpointStore,
    EventStore,
    FileArtifactStore,
    InMemoryArtifactStore,
    InMemoryCacheStore,
    InMemoryCheckpointStore,
    InMemoryEventStore,
    PostgresCheckpointStore,
    RedisCacheStore,
    RedisEventStore,
)
from schemas._base import StrictBaseModel

USE_REDIS_STORES_ENV = "DATA_ANALYSIS_AGENT_USE_REDIS_STORES"
USE_POSTGRES_CHECKPOINT_ENV = "DATA_ANALYSIS_AGENT_USE_POSTGRES_CHECKPOINT"
USE_FILE_ARTIFACT_STORE_ENV = "DATA_ANALYSIS_AGENT_USE_FILE_ARTIFACT_STORE"


class APISettings(StrictBaseModel):
    """Local API startup settings parsed from environment and CLI."""

    app_config: AppConfig = Field(default_factory=AppConfig)
    runner_backend: RunnerBackendName = "memory"
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    use_redis_stores: bool = False
    use_postgres_checkpoint: bool = False
    use_file_artifact_store: bool = False


def settings_from_env() -> APISettings:
    """Build local API settings from environment variables."""

    config = AppConfig.from_env()
    return APISettings(
        app_config=config,
        runner_backend=config.runner_backend,
        host=config.api_host,
        port=config.api_port,
        reload=config.api_reload,
        use_redis_stores=_env_flag(USE_REDIS_STORES_ENV, default=False),
        use_postgres_checkpoint=_env_flag(USE_POSTGRES_CHECKPOINT_ENV, default=False),
        use_file_artifact_store=_env_flag(USE_FILE_ARTIFACT_STORE_ENV, default=False),
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse local API CLI flags."""

    env_settings = settings_from_env()
    parser = argparse.ArgumentParser(description="Run the local FastAPI integration app.")
    parser.add_argument(
        "--runner-backend",
        choices=("memory", "celery"),
        default=env_settings.runner_backend,
        help=f"Runner backend. Defaults to ${RUNNER_BACKEND_ENV} or memory.",
    )
    parser.add_argument("--host", default=env_settings.host)
    parser.add_argument("--port", type=int, default=env_settings.port)
    parser.add_argument("--reload", action="store_true", default=env_settings.reload)
    parser.add_argument("--redis-url", default=env_settings.app_config.redis_url)
    parser.add_argument("--celery-broker-url", default=env_settings.app_config.celery_broker_url)
    parser.add_argument(
        "--celery-result-backend",
        default=env_settings.app_config.celery_result_backend,
    )
    parser.add_argument("--checkpoint-url", default=env_settings.app_config.checkpoint_url)
    parser.add_argument("--artifact-dir", default=env_settings.app_config.artifact_dir)
    parser.add_argument("--upload-dir", default=env_settings.app_config.upload_dir)
    parser.add_argument(
        "--max-upload-mb",
        type=int,
        default=env_settings.app_config.max_upload_mb,
    )
    parser.add_argument(
        "--allow-local-file-paths",
        action="store_true",
        default=env_settings.app_config.allow_local_file_paths,
        help="Allow /datasources/from-path in local development.",
    )
    parser.add_argument("--datasource-url", default=env_settings.app_config.datasource_url)
    parser.add_argument("--datasource-id", default=env_settings.app_config.datasource_id)
    parser.add_argument(
        "--session-store",
        choices=("memory", "sqlite", "sqlalchemy"),
        default=env_settings.app_config.session_store,
        help=f"Session history store. Defaults to ${SESSION_STORE_ENV} or memory.",
    )
    parser.add_argument(
        "--session-db-url",
        default=env_settings.app_config.session_db_url,
        help=(
            "SQLite/SQLAlchemy URL used when "
            f"${SESSION_STORE_ENV} is not memory. Defaults to ${SESSION_DB_URL_ENV}."
        ),
    )
    parser.add_argument(
        "--session-ttl-days",
        type=int,
        default=env_settings.app_config.session_ttl_days,
    )
    parser.add_argument(
        "--session-max-messages",
        type=int,
        default=env_settings.app_config.session_max_messages,
    )
    parser.add_argument(
        "--use-redis-stores",
        action="store_true",
        default=env_settings.use_redis_stores,
        help="Use Redis cache/event stores when redis-py and Redis are available.",
    )
    parser.add_argument(
        "--use-postgres-checkpoint",
        action="store_true",
        default=env_settings.use_postgres_checkpoint,
        help="Use Postgres checkpoint store when DATABASE_URL is configured.",
    )
    parser.add_argument(
        "--use-file-artifact-store",
        action="store_true",
        default=env_settings.use_file_artifact_store,
        help="Persist artifacts to the local file artifact store.",
    )
    return parser.parse_args(argv)


def settings_from_args(args: argparse.Namespace) -> APISettings:
    """Convert parsed CLI args to APISettings."""

    env_config = AppConfig.from_env()
    config = env_config.with_overrides(
        runner_backend=args.runner_backend,
        api_host=args.host,
        api_port=args.port,
        api_reload=args.reload,
        redis_url=args.redis_url,
        celery_broker_url=args.celery_broker_url,
        celery_result_backend=args.celery_result_backend,
        checkpoint_url=args.checkpoint_url,
        artifact_dir=args.artifact_dir,
        upload_dir=args.upload_dir,
        max_upload_mb=args.max_upload_mb,
        allow_local_file_paths=args.allow_local_file_paths,
        datasource_url=args.datasource_url,
        datasource_id=args.datasource_id,
        session_store=args.session_store,
        session_db_url=args.session_db_url,
        session_ttl_days=args.session_ttl_days,
        session_max_messages=args.session_max_messages,
    )
    return APISettings(
        app_config=config,
        runner_backend=args.runner_backend,
        host=args.host,
        port=args.port,
        reload=args.reload,
        use_redis_stores=args.use_redis_stores,
        use_postgres_checkpoint=args.use_postgres_checkpoint,
        use_file_artifact_store=args.use_file_artifact_store,
    )


def build_runner(settings: APISettings) -> WorkerBackend:
    """Build the selected local runner without changing app defaults."""

    config = settings.app_config.with_overrides(
        runner_backend=settings.runner_backend,
        api_host=settings.host,
        api_port=settings.port,
        api_reload=settings.reload,
    )
    if settings.runner_backend == "celery":
        stores = _celery_stores(config)
        return CeleryWorkerBackend(
            app_config=config,
            config=CeleryRunnerConfig.from_app_config(config),
            cache_store=stores[0],
            checkpoint_store=stores[1],
            event_store=stores[2],
            artifact_store=stores[3],
        )

    cache_store, event_store = _cache_and_event_stores(settings)
    checkpoint_store = _checkpoint_store(settings)
    artifact_store = _artifact_store(settings)
    return InMemoryJobRunner(
        datasource_registry=DataSourceRegistry.from_config(config, auto_register_demo=True),
        app_config=config,
        cache_store=cache_store,
        checkpoint_store=checkpoint_store,
        event_store=event_store,
        artifact_store=artifact_store,
    )


def build_app(settings: APISettings):
    """Build FastAPI app wired to the selected local runner."""

    return create_app(
        job_runner=build_runner(settings),
        session_store=build_session_store(settings.app_config),
        app_config=settings.app_config,
    )


def run_api(settings: APISettings) -> None:
    """Start uvicorn for manual local integration testing."""

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - manual local path only.
        raise RuntimeError("run_api.py requires uvicorn for local server startup.") from exc
    uvicorn.run(
        build_app(settings),
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for local FastAPI startup."""

    run_api(settings_from_args(parse_args(argv)))
    return 0


def _cache_and_event_stores(settings: APISettings) -> tuple[CacheStore, EventStore]:
    """Return memory or Redis-backed cache/event stores."""

    if settings.use_redis_stores:
        return RedisCacheStore(url=settings.app_config.effective_redis_url), RedisEventStore(
            url=settings.app_config.effective_redis_url
        )
    return InMemoryCacheStore(), InMemoryEventStore()


def _checkpoint_store(settings: APISettings) -> CheckpointStore:
    """Return memory or Postgres-backed checkpoint store."""

    if settings.use_postgres_checkpoint:
        return PostgresCheckpointStore(url=settings.app_config.effective_checkpoint_url)
    return InMemoryCheckpointStore()


def _artifact_store(settings: APISettings) -> ArtifactStore:
    """Return memory or local filesystem artifact store."""

    if settings.use_file_artifact_store:
        return FileArtifactStore(root_dir=settings.app_config.artifact_dir)
    return InMemoryArtifactStore()


def _celery_stores(
    config: AppConfig,
) -> tuple[CacheStore, CheckpointStore, EventStore, ArtifactStore]:
    """Return stores shared by API and Celery worker processes."""

    cache_store: CacheStore = (
        RedisCacheStore(url=config.effective_redis_url)
        if config.effective_redis_url
        else InMemoryCacheStore()
    )
    event_store: EventStore = (
        RedisEventStore(url=config.effective_redis_url)
        if config.effective_redis_url
        else InMemoryEventStore()
    )
    checkpoint_store: CheckpointStore = (
        PostgresCheckpointStore(url=config.effective_checkpoint_url)
        if config.effective_checkpoint_url
        else InMemoryCheckpointStore()
    )
    return (
        cache_store,
        checkpoint_store,
        event_store,
        FileArtifactStore(root_dir=config.artifact_dir),
    )


def _env_flag(name: str, *, default: bool) -> bool:
    """Parse common true/false environment variable values."""

    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())

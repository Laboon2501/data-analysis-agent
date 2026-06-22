"""Celery application factory for the optional asynchronous worker backend."""

from __future__ import annotations

import os
from typing import Any

from app.workers.celery_runner import CELERY_BROKER_URL_ENV, CeleryRunnerConfig

CELERY_APP_NAME = "data_analysis_agent"


def create_celery_app(config: CeleryRunnerConfig | None = None):
    """Create a Celery app from environment-backed configuration."""

    active_config = config or CeleryRunnerConfig.from_env()
    active_config.require_broker()
    try:
        from celery import Celery
    except ImportError as exc:  # pragma: no cover - only happens without project deps.
        raise RuntimeError("Celery backend requires the 'celery' package to be installed.") from exc

    app = Celery(
        CELERY_APP_NAME,
        broker=active_config.broker_url,
        backend=active_config.result_backend,
        include=["app.workers.celery_tasks"],
    )
    app.conf.update(
        task_default_queue=active_config.queue_name,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
    )
    return app


def celery_environment_configured() -> bool:
    """Return whether the current process has enough env to construct Celery."""

    return bool(os.getenv(CELERY_BROKER_URL_ENV))


celery_app: Any | None = create_celery_app() if celery_environment_configured() else None

__all__ = ["celery_app", "celery_environment_configured", "create_celery_app"]

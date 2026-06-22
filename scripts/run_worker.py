"""Local Celery worker command helper for manual integration checks."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import AppConfig
from app.workers import CeleryRunnerConfig
from app.workers.celery_runner import celery_submit_environment_ready

CELERY_APP_ENV = "DATA_ANALYSIS_AGENT_CELERY_APP"
WORKER_LOG_LEVEL_ENV = "DATA_ANALYSIS_AGENT_CELERY_LOG_LEVEL"
WORKER_CONCURRENCY_ENV = "DATA_ANALYSIS_AGENT_CELERY_CONCURRENCY"
WORKER_EXECUTE_ENV = "DATA_ANALYSIS_AGENT_WORKER_EXECUTE"
DEFAULT_CELERY_APP = "app.workers.celery_app:celery_app"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_CONCURRENCY = 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse local worker CLI flags."""

    parser = argparse.ArgumentParser(description="Print or run a local Celery worker command.")
    parser.add_argument("--app", default=os.getenv(CELERY_APP_ENV, DEFAULT_CELERY_APP))
    parser.add_argument(
        "--queue",
        default=os.getenv("DATA_ANALYSIS_AGENT_CELERY_QUEUE", "data-analysis-agent"),
    )
    parser.add_argument("--loglevel", default=os.getenv(WORKER_LOG_LEVEL_ENV, DEFAULT_LOG_LEVEL))
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.getenv(WORKER_CONCURRENCY_ENV, str(DEFAULT_CONCURRENCY))),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=_env_bool(WORKER_EXECUTE_ENV, default=False),
        help="Actually run the constructed command. Default prints only.",
    )
    return parser.parse_args(argv)


def build_worker_command(args: argparse.Namespace) -> list[str]:
    """Build a Celery worker command without executing it."""

    return [
        "celery",
        "-A",
        args.app,
        "worker",
        "-Q",
        args.queue,
        "--loglevel",
        args.loglevel,
        "--concurrency",
        str(args.concurrency),
    ]


def worker_environment_summary() -> dict[str, str | None]:
    """Return relevant environment-backed worker configuration."""

    app_config = AppConfig.from_env()
    config = CeleryRunnerConfig.from_app_config(app_config)
    return {
        "broker_url": config.broker_url,
        "result_backend": config.result_backend,
        "redis_url": app_config.effective_redis_url,
        "checkpoint_url": app_config.effective_checkpoint_url,
        "artifact_dir": app_config.artifact_dir,
        "upload_dir": app_config.upload_dir,
        "max_upload_mb": str(app_config.max_upload_mb),
        "allow_local_file_paths": str(app_config.allow_local_file_paths).lower(),
        "datasource_url": app_config.datasource_url,
        "queue_name": config.queue_name,
        "task_name": config.task_name,
        "celery_app": os.getenv(CELERY_APP_ENV, DEFAULT_CELERY_APP),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Print the Celery worker command or run it when explicitly requested."""

    args = parse_args(argv)
    command = build_worker_command(args)
    print("Worker environment:")
    for key, value in worker_environment_summary().items():
        print(f"  {key}: {value}")
    print("Celery worker command:")
    print("  " + " ".join(command))
    if not args.execute:
        print("Print-only mode. Pass --execute to run the command locally.")
        return 0
    if not celery_submit_environment_ready():
        print(
            "Celery worker cannot start: configure DATA_ANALYSIS_AGENT_CELERY_BROKER_URL "
            "and shared Redis stores through DATA_ANALYSIS_AGENT_REDIS_URL or a Redis broker URL."
        )
        return 2
    return subprocess.call(command)


def _env_bool(name: str, *, default: bool) -> bool:
    """Parse common true/false environment values."""

    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    raise SystemExit(main())

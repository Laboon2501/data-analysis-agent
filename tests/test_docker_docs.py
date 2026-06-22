"""Tests for Docker and deployment documentation entrypoints."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_docker_files_exist_and_use_safe_defaults() -> None:
    """Docker files should document memory and Celery runtime paths."""

    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    memory_compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    celery_compose = (REPO_ROOT / "docker-compose.celery.yml").read_text(encoding="utf-8")

    assert "python:3.11-slim" in dockerfile
    assert "python -m pip install -e ." in dockerfile
    assert "scripts/run_api.py" in dockerfile
    assert ".env" in dockerignore
    assert ".idea/" in dockerignore
    assert "artifacts/" in dockerignore
    assert "DATA_ANALYSIS_AGENT_RUNNER_BACKEND: memory" in memory_compose
    assert "DATA_ANALYSIS_AGENT_USE_FILE_ARTIFACT_STORE" in memory_compose
    assert "artifact_data:/app/artifacts" in memory_compose
    assert "DATA_ANALYSIS_AGENT_RUNNER_BACKEND: celery" in celery_compose
    assert "upload_data:/app/uploads" in celery_compose
    assert "DATA_ANALYSIS_AGENT_UPLOAD_DIR" in celery_compose
    assert "DATA_ANALYSIS_AGENT_SESSION_STORE: sqlalchemy" in celery_compose
    assert "DATA_ANALYSIS_AGENT_SESSION_DB_URL" in celery_compose
    assert "DATA_ANALYSIS_AGENT_CHECKPOINT_URL" in celery_compose
    assert "redis:" in celery_compose
    assert "postgres:" in celery_compose
    assert "worker:" in celery_compose
    assert "DATA_ANALYSIS_AGENT_LLM_PROVIDER" not in memory_compose


def test_deployment_docs_cover_runtime_requirements() -> None:
    """Deployment docs should mention health, artifact volume, and safety boundaries."""

    text = (REPO_ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")

    for keyword in (
        "Memory Backend Compose",
        "Celery Backend Compose",
        "artifact_data",
        "upload_data",
        "GET /health",
        "GET /health/runtime",
        "DATA_ANALYSIS_AGENT_ARTIFACT_DIR",
        "DATA_ANALYSIS_AGENT_UPLOAD_DIR",
        "DATA_ANALYSIS_AGENT_CELERY_BROKER_URL",
        "Default LLM strategy remains rule-based",
        "Do not commit `.env`",
    ):
        assert keyword in text


def test_readme_and_commands_reference_client_and_docker_entrypoints() -> None:
    """Onboarding docs should expose client and Docker commands."""

    combined = "\n".join(
        [
            (REPO_ROOT / "README.md").read_text(encoding="utf-8"),
            (REPO_ROOT / "docs" / "commands.md").read_text(encoding="utf-8"),
            (REPO_ROOT / "docs" / "local_run.md").read_text(encoding="utf-8"),
        ]
    )

    for keyword in (
        "examples/client/minimal_client.py",
        "examples/client/demo_flow_client.py",
        "docker compose up --build api",
        "docker compose -f docker-compose.celery.yml up --build",
        "docs/deployment.md",
    ):
        assert keyword in combined

"""Release readiness checks for v0.2.0-alpha."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from app.api.main import create_app
from schemas.event import EventType

ROOT_DIR = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT_DIR / "examples" / "web"


def test_package_version_matches_alpha_release() -> None:
    """The package uses the PEP 440 alpha version for the v0.2.0-alpha tag."""

    pyproject = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["version"] == "0.2.0a0"


def test_release_documents_exist() -> None:
    """Key release and onboarding documents must exist before tagging."""

    required_docs = [
        "README.md",
        "docs/api.md",
        "docs/events.md",
        "docs/deployment.md",
        "docs/commands.md",
        "docs/local_run.md",
        "docs/frontend_flow.md",
        "docs/release_checklist.md",
        "docs/release_notes_v0.1.0.md",
        "docs/release_notes_v0.2.0-alpha.md",
        ".env.example",
        ".github/workflows/ci.yml",
    ]

    for relative_path in required_docs:
        assert (ROOT_DIR / relative_path).exists(), relative_path


def test_release_docs_identify_v020_alpha_preview() -> None:
    """README and release notes should identify this as an alpha preview."""

    readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
    release_notes = (ROOT_DIR / "docs/release_notes_v0.2.0-alpha.md").read_text(encoding="utf-8")
    checklist = (ROOT_DIR / "docs/release_checklist.md").read_text(encoding="utf-8")

    assert "v0.2.0-alpha technical preview" in readme
    assert "Release Notes v0.2.0-alpha Technical Preview" in release_notes
    assert "v0.2.0-alpha Release Checklist" in checklist
    assert "0.2.0a0" in release_notes


def test_mcp_version_metadata_matches_alpha_release() -> None:
    """MCP smoke metadata should not advertise the previous release version."""

    transport = (ROOT_DIR / "mcp" / "transport.py").read_text(encoding="utf-8")
    demo_server = (ROOT_DIR / "examples" / "mcp" / "demo_mcp_server.py").read_text(encoding="utf-8")

    assert '"version": "0.2.0-alpha"' in transport
    assert '"version": "0.2.0-alpha"' in demo_server


def test_local_secret_ide_cache_and_runtime_files_are_not_tracked() -> None:
    """Local secrets, IDE state, caches, artifacts, uploads, and SQLite DBs stay untracked."""

    tracked_files = _git_ls_files()
    forbidden = [
        path
        for path in tracked_files
        if path == ".env"
        or (path.startswith(".env.") and path != ".env.example")
        or path.startswith(".idea/")
        or path.startswith(".vscode/")
        or "__pycache__/" in path
        or path.endswith(".pyc")
        or path.startswith("artifacts/")
        or path.startswith("uploads/")
        or path.startswith("outputs/")
        or path.startswith("tmp/")
        or path.startswith("temp/")
        or (path.startswith("demo/") and path.endswith(".sqlite"))
    ]

    assert forbidden == []


def test_readme_contains_release_candidate_commands() -> None:
    """README keeps the new-developer and release-verification command surface."""

    readme = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
    required_commands = [
        'python -m pip install -e ".[dev]"',
        "python -m pytest",
        "python -m evals.runner",
        "python -m ruff check .",
        "python -m ruff format --check .",
        "python scripts/create_demo_db.py",
        "python scripts/run_demo_flow.py",
        "python scripts/run_api.py",
        "python scripts/run_llm_smoke.py",
        "python scripts/run_llm_eval.py",
        "python scripts/run_mcp_smoke.py",
        "python scripts/run_integration_smoke.py",
        "python examples/client/minimal_client.py",
        "python examples/client/demo_flow_client.py",
        "docker compose up --build api",
        "docker compose -f docker-compose.celery.yml up --build",
    ]

    for command in required_commands:
        assert command in readme, command


def test_docs_api_matches_fastapi_routes() -> None:
    """API docs cover the main FastAPI routes exposed to frontend clients."""

    docs_api = (ROOT_DIR / "docs/api.md").read_text(encoding="utf-8")
    documented_routes = {
        "/health",
        "/health/runtime",
        "/llm/status",
        "/sessions",
        "/sessions/cleanup",
        "/sessions/{session_id}",
        "/sessions/{session_id}/messages",
        "/sessions/{session_id}/jobs",
        "/sessions/{session_id}/llm",
        "/datasources",
        "/datasources/from-path",
        "/datasources/upload",
        "/datasources/{datasource_id}",
        "/datasources/{datasource_id}/profile",
        "/sessions/{session_id}/datasource",
        "/sessions/{session_id}/chat",
        "/jobs/{job_id}",
        "/jobs/{job_id}/events",
        "/jobs/{job_id}/events/stream",
        "/jobs/{job_id}/approve",
        "/jobs/{job_id}/cancel",
        "/artifacts/{artifact_id}",
        "/artifacts/{artifact_id}/content",
    }
    app_routes = {
        route.path
        for route in create_app().routes
        if route.path not in {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    }

    assert documented_routes <= app_routes
    for route in documented_routes:
        assert route in docs_api


def test_docs_events_cover_all_event_types() -> None:
    """Event docs cover every schemas.event.EventType value."""

    docs_events = (ROOT_DIR / "docs/events.md").read_text(encoding="utf-8")

    for event_type in EventType:
        assert f"## {event_type.value}" in docs_events


def test_env_example_covers_key_runtime_configuration() -> None:
    """The sample env file covers local, distributed, datasource, and LLM knobs."""

    env_example = (ROOT_DIR / ".env.example").read_text(encoding="utf-8")
    required_variables = [
        "DATA_ANALYSIS_AGENT_RUNNER_BACKEND",
        "DATA_ANALYSIS_AGENT_REDIS_URL",
        "DATA_ANALYSIS_AGENT_CELERY_BROKER_URL",
        "DATA_ANALYSIS_AGENT_CELERY_RESULT_BACKEND",
        "DATA_ANALYSIS_AGENT_CHECKPOINT_URL",
        "DATA_ANALYSIS_AGENT_DATABASE_URL",
        "DATA_ANALYSIS_AGENT_DATASOURCE_URL",
        "DATA_ANALYSIS_AGENT_DATASOURCE_ID",
        "DATA_ANALYSIS_AGENT_ARTIFACT_DIR",
        "DATA_ANALYSIS_AGENT_UPLOAD_DIR",
        "DATA_ANALYSIS_AGENT_MAX_UPLOAD_MB",
        "DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS",
        "DATA_ANALYSIS_AGENT_SESSION_STORE",
        "DATA_ANALYSIS_AGENT_SESSION_DB_URL",
        "DATA_ANALYSIS_AGENT_SESSION_TTL_DAYS",
        "DATA_ANALYSIS_AGENT_SESSION_MAX_MESSAGES",
        "DATA_ANALYSIS_AGENT_LLM_PROVIDER",
        "DATA_ANALYSIS_AGENT_LLM_MODEL",
        "DATA_ANALYSIS_AGENT_LLM_BASE_URL",
        "DATA_ANALYSIS_AGENT_LLM_API_KEY_ENV",
    ]

    for variable in required_variables:
        assert variable in env_example


def test_web_ui_has_no_react_vue_or_build_chain() -> None:
    """The release Web UI remains vanilla HTML, CSS, and JavaScript."""

    assert (WEB_ROOT / "index.html").exists()
    assert (WEB_ROOT / "app.js").exists()
    assert (WEB_ROOT / "styles.css").exists()
    assert not (WEB_ROOT / "package.json").exists()

    app_js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    index_html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    forbidden_tokens = [
        "import React",
        "ReactDOM",
        "createApp(",
        "new Vue",
        "vite/client",
        "webpack://",
    ]

    for token in forbidden_tokens:
        assert token not in app_js
        assert token not in index_html


def _git_ls_files() -> list[str]:
    """Return tracked git paths."""

    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]

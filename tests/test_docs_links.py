"""Documentation contract tests for API, events, and frontend flow docs."""

from __future__ import annotations

import re
from pathlib import Path

from app.api import create_app
from schemas.event import EventType

DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
API_DOC = DOCS_DIR / "api.md"
EVENTS_DOC = DOCS_DIR / "events.md"
FRONTEND_FLOW_DOC = DOCS_DIR / "frontend_flow.md"
LOCAL_RUN_DOC = DOCS_DIR / "local_run.md"

EXPECTED_ENDPOINTS = {
    ("GET", "/health"),
    ("GET", "/health/runtime"),
    ("GET", "/sessions"),
    ("POST", "/sessions"),
    ("POST", "/sessions/cleanup"),
    ("GET", "/sessions/{session_id}"),
    ("DELETE", "/sessions/{session_id}"),
    ("GET", "/sessions/{session_id}/messages"),
    ("POST", "/sessions/{session_id}/messages"),
    ("GET", "/sessions/{session_id}/jobs"),
    ("GET", "/llm/status"),
    ("GET", "/sessions/{session_id}/llm"),
    ("POST", "/sessions/{session_id}/llm"),
    ("GET", "/datasources"),
    ("POST", "/datasources"),
    ("POST", "/datasources/from-path"),
    ("POST", "/datasources/upload"),
    ("GET", "/datasources/{datasource_id}"),
    ("POST", "/datasources/{datasource_id}/profile"),
    ("POST", "/sessions/{session_id}/datasource"),
    ("GET", "/sessions/{session_id}/datasource"),
    ("POST", "/sessions/{session_id}/chat"),
    ("GET", "/jobs/{job_id}"),
    ("GET", "/jobs/{job_id}/events"),
    ("GET", "/jobs/{job_id}/events/stream"),
    ("POST", "/jobs/{job_id}/approve"),
    ("POST", "/jobs/{job_id}/cancel"),
    ("GET", "/artifacts/{artifact_id}"),
    ("GET", "/artifacts/{artifact_id}/content"),
}


def test_api_doc_endpoints_match_fastapi_routes() -> None:
    """Primary endpoints should be documented and present in FastAPI routes."""

    api_text = API_DOC.read_text(encoding="utf-8")
    documented = set(re.findall(r"## (GET|POST|DELETE) (`?/[^\n`]+`?)", api_text))
    documented = {(method, path.strip("`")) for method, path in documented}

    app = create_app()
    actual_routes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if method in {"GET", "POST", "DELETE"}
    }

    assert EXPECTED_ENDPOINTS <= documented
    assert EXPECTED_ENDPOINTS <= actual_routes


def test_event_doc_covers_required_frontend_events() -> None:
    """Events docs should cover frontend-visible event types."""

    events_text = EVENTS_DOC.read_text(encoding="utf-8")
    required_events = {
        "node_start",
        "node_end",
        "error",
        "done",
        "stopped",
        "chart_ref",
        "artifact_ref",
        "human_request",
        "llm_start",
        "llm_end",
        "llm_error",
        "llm_fallback",
        "llm_json_invalid",
    }

    for event_name in required_events:
        assert f"## {event_name}" in events_text
        assert f'"event_type": "{event_name}"' in events_text
        assert event_name in {event_type.value for event_type in EventType}


def test_docs_do_not_embed_large_artifact_payload_examples() -> None:
    """Docs should not encourage embedding artifact bodies in events/history."""

    combined_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (API_DOC, EVENTS_DOC, FRONTEND_FLOW_DOC, LOCAL_RUN_DOC)
    )
    blocked_snippets = {
        '"chart_html": "<div',
        '"file_content":',
        '"file_bytes":',
        '"binary":',
        '"data_url": "data:',
    }

    for snippet in blocked_snippets:
        assert snippet not in combined_text


def test_frontend_and_local_run_docs_reference_primary_flows() -> None:
    """Frontend and local-run docs should cover the primary integration flows."""

    frontend_text = FRONTEND_FLOW_DOC.read_text(encoding="utf-8")
    local_run_text = LOCAL_RUN_DOC.read_text(encoding="utf-8")

    for keyword in (
        "明确问题分析流程",
        "开放探索流程",
        "报告 / PPT / Excel / Dashboard 导出确认流程",
        "Artifact 下载流程",
        "Cancel 流程",
        "Human Request Approve 流程",
        "Minimal Client Example",
    ):
        assert keyword in frontend_text

    for keyword in (
        "Memory Backend Local Run",
        "DeepSeek / OpenAI-Compatible Smoke Test",
        "MCP Smoke Test",
        "Redis / Celery Integration Smoke Test",
        "Docker Memory Backend",
        "Docker Celery Backend",
        "Common Environment Variables",
    ):
        assert keyword in local_run_text

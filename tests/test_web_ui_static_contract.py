"""Static contract checks for examples/web without starting a browser or API."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "examples" / "web"


def test_web_ui_subscribes_to_named_sse_events() -> None:
    """The UI should use EventSource and handle the event types documented by the API."""

    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "new EventSource" in text
    for event_type in (
        "node_start",
        "node_end",
        "text_delta",
        "chart_ref",
        "artifact_ref",
        "human_request",
        "error",
        "done",
        "stopped",
        "llm_start",
        "llm_fallback",
    ):
        assert event_type in text


def test_web_ui_omits_large_payload_keys_from_event_display() -> None:
    """The event timeline should not render large artifact bodies."""

    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "sanitizeEventPayload" in text
    for key in ("chart_html", "file_content", "file_bytes", "data_url"):
        assert key in text
    assert "<omitted>" in text


def test_web_ui_ignores_native_eventsource_error_without_payload() -> None:
    """Native EventSource close/error callbacks should not appear as `{}` job errors."""

    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'eventType === "error" && !event.data' in text


def test_web_ui_declares_expected_page_regions() -> None:
    """The static page should include the core frontend integration regions."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    for element_id in (
        "message-list",
        "inline-approval-panel",
        "approval-shortcuts",
        "event-timeline",
        "sql-output",
        "artifact-list",
        "dashboard-renderer",
        "dashboard-renderer-status",
        "human-request-card",
        "cancel-job-btn",
        "api-health",
        "runtime-health",
        "top-runner-backend",
        "top-datasource-status",
        "top-current-datasource",
        "top-llm-mode",
        "top-llm-provider-model",
        "top-llm-enabled-nodes",
        "top-llm-api-key",
        "top-session-title",
        "top-session-id",
        "session-list",
        "session-panel-status",
        "refresh-sessions-btn",
        "delete-session-btn",
        "session-title-input",
        "rename-session-btn",
        "session-job-list",
        "datasource-select",
        "datasource-list",
        "refresh-datasources-btn",
        "set-session-datasource-btn",
        "profile-datasource-btn",
        "register-datasource-btn",
        "register-file-path-btn",
        "upload-datasource-btn",
        "file-path-input",
        "datasource-upload-input",
        "file-path-mode-note",
        "upload-format-note",
        "upload-next-step-note",
        "toggle-left-panel-btn",
        "toggle-right-panel-btn",
        "composer-keyboard-hint",
        "close-preview-btn",
        "llm-mode-select",
        "llm-mode-fixed-label",
        "llm-node-planner",
        "llm-node-sql-drafter",
        "llm-node-insight-writer",
        "save-llm-config-btn",
        "llm-provider-select",
        "llm-model-input",
        "llm-base-url-input",
        "llm-api-key-input",
        "save-global-llm-config-btn",
        "test-llm-config-btn",
        "llm-config-status-panel",
        "llm-call-count",
        "llm-fallback-count",
        "router-decision-source",
        "router-decision-intent",
        "router-decision-confidence",
        "router-decision-reason",
    ):
        assert f'id="{element_id}"' in html

    assert '<details id="developer-details" class="developer-details">' in html
    assert '<details class="developer-details" open>' not in html
    assert "developer-details" in html


def test_web_ui_has_product_prompts_and_inline_approval_controls() -> None:
    """The product UI should keep approvals near chat and expose example prompts."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert html.count("data-prompt=") >= 4
    assert "quick-prompts" in html

    for label in ("Yes / Confirm", "No / Cancel", "Excel", "PPT", "Dashboard", "Report"):
        assert label in text

    for fragment in (
        "renderApprovalShortcuts",
        "upsertApprovalMessage",
        "approvalActions",
        "approvalCommand",
        "inline_approval",
    ):
        assert fragment in text


def test_web_ui_groups_artifacts_by_product_type() -> None:
    """Artifacts should be grouped into product-facing buckets."""

    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for group_title in ("Charts", "Reports", "Excel", "PPT", "Dashboards"):
        assert group_title in text
    assert "artifactGroups" in text
    assert "renderArtifactItem" in text


def test_web_ui_javascript_has_balanced_basic_structure() -> None:
    """A light syntax smoke check catches accidental truncation of the JS file."""

    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert text.count("{") == text.count("}")
    assert text.count("(") == text.count(")")
    assert text.count("[") == text.count("]")
    assert re.search(r"window\.DataAnalysisWebUI\s*=", text)


def test_api_allows_static_web_ui_localhost_origin() -> None:
    """The documented static server origin should be allowed by local API CORS."""

    text = (REPO_ROOT / "app" / "api" / "main.py").read_text(encoding="utf-8")

    assert "CORSMiddleware" in text
    assert "http://127.0.0.1:5173" in text
    assert "http://localhost:5173" in text


def test_web_ui_uses_datasource_management_endpoints() -> None:
    """Web UI should call datasource registry and session datasource endpoints."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for endpoint in (
        "/datasources",
        "/datasources/from-path",
        "/datasources/upload",
        "/profile",
        "/datasource",
    ):
        assert endpoint in text
    assert "refreshDatasources" in text
    assert "setCurrentDatasource" in text
    assert "registerDatasource" in text
    assert "registerFilePathDatasource" in text
    assert "uploadDatasourceFile" in text
    assert "FormData" in text
    assert "CSV/Excel" in html
    assert "Parquet is optional and requires pyarrow" in html
    assert "DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS" in html
    assert "friendlyDatasourceError" in text
    assert "Maximum upload size" in text


def test_web_ui_uses_session_history_endpoints() -> None:
    """Web UI should load, switch, and delete user-visible sessions."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for endpoint in (
        "/sessions",
        "/messages",
        "/jobs",
    ):
        assert endpoint in text
    for function_name in (
        "refreshSessions",
        "loadSession",
        "deleteCurrentSession",
        "refreshSessionMessages",
        "refreshSessionJobs",
    ):
        assert function_name in text
    assert "artifact_refs" in text
    assert "chart_artifact_refs" in text
    assert "top-session-store" in html
    assert "current-session-message-count" in html
    assert "current-session-updated-at" in html
    assert "window.confirm" in text
    assert "Memory history is temporary" in text


def test_web_ui_uses_llm_status_and_session_config_endpoints() -> None:
    """Web UI should expose safe LLM status/config controls without API keys."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for endpoint in (
        "/llm/status",
        "/llm",
    ):
        assert endpoint in text
    for node_name in ("planner", "sql_drafter", "insight_writer"):
        assert node_name in html
        assert node_name in text
    assert "llm-node-router" not in html
    assert 'value="fake_llm"' not in html
    assert 'FIXED_LLM_MODE = "real_llm"' in text
    assert 'LLM_NODE_ALIASES = ["planner", "sql_drafter", "insight_writer"]' in text
    assert "refreshLlmStatus" in text
    assert "saveLlmConfig" in text
    assert "saveGlobalLlmConfig" in text
    assert "testLlmConfig" in text
    assert "api_key_configured" in text
    assert "friendlyNetworkError" in text
    assert "DEFAULT_LLM_ENABLED_NODES" in text
    assert '["planner", "sql_drafter", "insight_writer"]' in text
    assert "真实模型需要先保存 Provider / Model / Base URL / API key" in html
    assert "Provider config saved; API key configured" in text
    old_env_only_message = (
        "Real LLM mode requires an API key configured in backend environment variables"
    )
    assert old_env_only_message not in html
    assert "sk-" not in html
    assert "sk-" not in text


def test_web_ui_displays_router_decision_in_developer_details() -> None:
    """Developer details should expose route source, intent, confidence and reason."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "router-decision-block" in html
    assert "Router decision" in html
    assert "renderRouterDecision" in text
    assert "clearRouterDecision" in text
    assert "router_decision" in text


def test_web_ui_keeps_developer_details_and_sidebars_collapsible() -> None:
    """Debug-heavy regions should be hidden or collapsible in the product UI."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert '<details id="developer-details" class="developer-details">' in html
    assert "closeActivePreviewOrDetails" in text
    assert 'event.key === "Escape"' in text
    assert "toggleSidebar" in text
    assert "left-panel-collapsed" in text
    assert "right-panel-collapsed" in text
    assert "left-panel-collapsed" in css
    assert "right-panel-collapsed" in css

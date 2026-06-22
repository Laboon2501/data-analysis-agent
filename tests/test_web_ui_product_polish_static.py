"""Additional static checks for the productized Web UI polish."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "examples" / "web"


def test_web_ui_contains_productized_llm_config_controls() -> None:
    """The UI should expose provider config without displaying saved keys."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for element_id in (
        "llm-provider-select",
        "llm-model-input",
        "llm-base-url-input",
        "llm-api-key-input",
        "save-global-llm-config-btn",
        "test-llm-config-btn",
        "llm-config-status-panel",
    ):
        assert f'id="{element_id}"' in html
    for endpoint in ("/llm/config", "/llm/test", "/llm/status"):
        assert endpoint in text
    for provider in ("deepseek", "openai_compatible", "openai", "custom"):
        assert provider in html
    assert "sk-" not in html
    assert "sk-" not in text


def test_web_ui_uses_session_titles_instead_of_uuid_header() -> None:
    """The visible header/session list should prefer friendly titles."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="top-session-title"' in html
    assert 'id="session-title-input"' in html
    assert 'id="rename-session-btn"' in html
    assert 'id="top-session-id"' in html  # Developer details only.
    assert 'Session: <strong id="top-session-id"' not in html
    assert 'session.title || "新对话"' in text
    assert "session.title || session.session_id" not in text
    assert "PATCH" in text
    assert "`/sessions/${encodeURIComponent(state.sessionId)}`" in text


def test_web_ui_wraps_failed_to_fetch_for_humans() -> None:
    """Network failures should be shown as product-facing guidance."""

    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "friendlyNetworkError" in text
    assert "后端未连接，请确认 FastAPI 已启动并检查 API Base URL。" in text
    assert "Failed to fetch" in text


def test_web_ui_delete_last_session_does_not_auto_create() -> None:
    """Deleting the final session should show an empty state instead of calling New Session."""

    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "showNoSessionState" in text
    assert "await startNewSession();" not in text
    assert "mostRecentSession" in text
    assert "暂无会话，请新建会话开始分析。" in text


def test_web_ui_header_status_uses_wrapping_chip_layout() -> None:
    """Header status tags should use normal wrapping layout, not overlay-prone positioning."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "status-chip-row" in html
    assert "status-chip" in html
    assert "flex-wrap: wrap" in css
    assert "grid-template-rows: auto minmax(0, 1fr)" in css
    assert "position: absolute" not in css[css.find(".topbar") : css.find(".left-panel")]

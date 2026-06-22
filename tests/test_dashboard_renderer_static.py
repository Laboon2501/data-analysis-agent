"""Static checks for the lightweight dashboard renderer in examples/web."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "examples" / "web"


def test_web_ui_declares_dashboard_renderer_region() -> None:
    """The static UI should expose a dashboard renderer without a new API route."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert 'id="dashboard-renderer"' in html
    assert 'id="dashboard-renderer-status"' in html
    assert "renderDashboardArtifact" in app
    assert "renderDashboardSpec" in app
    assert "/artifacts/" in app
    assert "/dashboard" not in app


def test_web_ui_renders_chart_artifact_preview_from_json() -> None:
    """Chart artifacts should be previewed client-side from artifact JSON only."""

    app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    for fragment in (
        "previewChartArtifact",
        "renderChartPreviewFromSpec",
        "normalizeChartArtifact",
        "lineMarkup",
        "barMarkup",
        "chart_artifact_ref",
        "application/vnd.data-analysis-agent.chart+json",
    ):
        assert fragment in app


def test_dashboard_renderer_uses_artifact_refs_without_large_payloads() -> None:
    """Dashboard rendering should keep artifact bodies out of events/history."""

    app = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    docs = (REPO_ROOT / "docs" / "frontend_flow.md").read_text(encoding="utf-8")

    assert "normalizeArtifactRef" in app
    assert "artifact:<id>" in app
    assert "fetchArtifactContent" in app
    assert "OMITTED_PAYLOAD_KEYS" in app
    for key in ("chart_html", "file_content", "file_bytes", "data_url", "content"):
        assert key in app
    assert "Dashboard renderer 不新增后端 API" in docs


def test_web_ui_has_no_frontend_framework_or_build_chain() -> None:
    """Phase 40 should remain vanilla static HTML/CSS/JS."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8").lower()
    app = (WEB_ROOT / "app.js").read_text(encoding="utf-8").lower()

    forbidden = (
        "react.development",
        "react.production",
        "vue.global",
        "cdn.jsdelivr.net/npm/vue",
        "unpkg.com/react",
        "vite/client",
        "webpack",
    )
    for token in forbidden:
        assert token not in html
        assert token not in app
    assert not (WEB_ROOT / "package.json").exists()

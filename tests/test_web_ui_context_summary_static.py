"""Static Web UI checks for compact context summary panel."""

from pathlib import Path


def test_web_ui_contains_context_summary_developer_panel() -> None:
    """Developer details should expose compact context without framework tooling."""

    html = Path("examples/web/index.html").read_text(encoding="utf-8")
    js = Path("examples/web/app.js").read_text(encoding="utf-8")

    assert "context-summary-block" in html
    assert "context-summary-datasource" in html
    assert "context-summary-field-count" in html
    assert "renderContextSummary" in js
    assert "context_summary" in js
    assert "React" not in html + js
    assert "Vue" not in html + js

"""Static Web UI checks for progress and timing diagnostics."""

from __future__ import annotations

from pathlib import Path

WEB_DIR = Path("examples/web")


def test_web_ui_contains_timing_panel_and_progress_helpers() -> None:
    """Developer details should expose timing while chat shows progress text."""

    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert 'id="timing-panel"' in html
    assert 'id="timing-table-body"' in html
    assert "LLM calls total" in html
    assert "renderProgressDelta" in js
    assert "clearProgressDelta" in js
    assert "collectTiming" in js
    assert "duration_ms" in js
    assert "timing_records" in js

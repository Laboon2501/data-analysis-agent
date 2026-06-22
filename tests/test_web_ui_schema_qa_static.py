"""Static Web UI checks for schema QA rendering."""

from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1] / "examples" / "web"


def test_web_ui_renders_schema_qa_cards() -> None:
    """Schema QA responses should show field cards in the chat stream."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    js = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    assert "schema_qa_result" in js
    assert "appendSchemaQaMessage" in js
    assert "schema-qa-card" in js
    assert "schema-qa-card" in css
    assert "message-list" in html
    assert "execute_sql" not in js[js.find("appendSchemaQaMessage") : js.find("pushError")]

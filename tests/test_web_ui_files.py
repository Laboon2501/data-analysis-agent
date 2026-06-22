"""Static checks for the browser Web UI example."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "examples" / "web"


def test_web_ui_files_exist() -> None:
    """The release UI example should include all documented static files."""

    for relative_path in ("index.html", "app.js", "styles.css", "README.md"):
        assert (WEB_ROOT / relative_path).is_file()


def test_web_ui_uses_current_fastapi_contract() -> None:
    """The static UI should target current FastAPI routes, not upstream Flask routes."""

    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    required_fragments = (
        "/sessions/",
        "/messages",
        "/chat",
        "/jobs",
        "/jobs/",
        "/events",
        "/events/stream",
        "/approve",
        "/cancel",
        "/artifacts/",
        "/content",
        "/health",
        "/health/runtime",
    )
    for fragment in required_fragments:
        assert fragment in text

    forbidden_fragments = (
        "/api/session/",
        "/api/saved-sessions",
        "/api/datasource-configs",
        "BusinessAgent",
    )
    for fragment in forbidden_fragments:
        assert fragment not in text


def test_web_ui_artifact_and_confirm_contracts_are_present() -> None:
    """The UI should normalize artifact refs and expose export confirm commands."""

    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "normalizeArtifactRef" in text
    assert "artifact:<id>" in text
    assert "artifact_ref" in text
    assert "chart_artifact_ref" in text
    for command in ("report_confirm", "excel_confirm", "ppt_confirm", "dashboard_confirm"):
        assert command in text


def test_web_ui_does_not_include_real_secret_placeholders() -> None:
    """The static UI must not ship real API keys or local private env content."""

    combined = "\n".join(
        (WEB_ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in ("index.html", "app.js", "styles.css", "README.md")
    )

    forbidden = ("sk-", "AKIA", "BEGIN PRIVATE KEY", "DEEPSEEK_API_KEY=", "OPENAI_API_KEY=")
    for token in forbidden:
        assert token not in combined

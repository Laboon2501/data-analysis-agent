"""Static accessibility checks for the lightweight web UI."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = REPO_ROOT / "examples" / "web"


def test_main_controls_expose_accessible_labels_and_status_text() -> None:
    """Core controls should have labels or live status text for assistive tech."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    for fragment in (
        'aria-label="发送消息"',
        'aria-label="消息输入框"',
        'aria-label="取消当前任务"',
        'aria-label="Pending human approval"',
        'role="status"',
        'aria-live="polite"',
        'role="alert"',
        "composer-keyboard-hint",
    ):
        assert fragment in html


def test_keyboard_shortcuts_and_focus_management_are_present() -> None:
    """The UI should support Enter, Shift+Enter, Esc, and approval focus."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "Enter 发送，Shift+Enter 换行" in html
    assert 'event.key === "Enter" && !event.shiftKey' in text
    assert 'event.key === "Escape"' in text
    assert ".focus({ preventScroll: false })" in text
    assert "审批选项：" in text
    assert "快捷审批：" in text


def test_responsive_sidebar_and_preview_controls_exist() -> None:
    """Narrow screens should be able to collapse side panels and close previews."""

    html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")
    css = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")

    for element_id in ("toggle-left-panel-btn", "toggle-right-panel-btn", "close-preview-btn"):
        assert f'id="{element_id}"' in html
    assert "toggleSidebar" in text
    assert "closeActivePreview" in text
    assert "@media (max-width: 1180px)" in css
    assert "@media (max-width: 780px)" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css


def test_artifact_download_errors_are_user_visible() -> None:
    """Downloads should go through JS so failed content fetches can be explained."""

    text = (WEB_ROOT / "app.js").read_text(encoding="utf-8")

    assert "downloadArtifact" in text
    assert "Artifact download failed" in text
    assert "response.blob()" in text
    assert "downloadName(metadata, artifactId)" in text


def test_web_ui_stays_framework_free() -> None:
    """The release example should remain static HTML/CSS/JS with no build chain."""

    combined = "\n".join(
        (WEB_ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in ("index.html", "app.js", "styles.css", "README.md")
    )

    forbidden = (
        "react.development",
        "react.production",
        "vue.global",
        "vite/client",
        "webpack://",
        "next/dist",
    )
    lowered = combined.lower()
    for token in forbidden:
        assert token not in lowered

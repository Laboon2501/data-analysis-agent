"""Static checks for Chinese Web UI text and encoding."""

from __future__ import annotations

from pathlib import Path

WEB_DIR = Path("examples/web")


def test_web_ui_declares_utf8_and_has_chinese_placeholder() -> None:
    """The static UI should render Chinese composer text without mojibake."""

    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert '<meta charset="UTF-8">' in html
    assert "输入问题，Enter 发送，Shift+Enter 换行" in html
    assert "Esc 关闭图表 / Dashboard 预览或折叠开发者详情。" in html
    assert "输入问题，Enter 发送，Shift+Enter 换行" in js
    assert "后端未连接，请先启动 FastAPI" in js


def test_web_ui_static_text_has_no_question_mark_mojibake() -> None:
    """Question mark mojibake should not appear in the Web UI sources."""

    for path in [WEB_DIR / "index.html", WEB_DIR / "app.js"]:
        text = path.read_text(encoding="utf-8")
        assert "????" not in text

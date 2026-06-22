"""Static checks for the Web UI SQL panel state."""

from pathlib import Path


def test_sql_panel_only_shows_primary_direct_analysis_sql() -> None:
    """开放探索、schema QA 和导出确认不应把内部 SQL 显示成主 SQL。"""

    script = Path("examples/web/app.js").read_text(encoding="utf-8")

    assert 'finalState?.intent === "direct_analysis"' in script
    assert 'finalState?.command === "analyze"' in script
    assert "该任务包含多个内部查询，请在开发者详情中查看。" in script
    assert '"未生成 SQL"' in script
    assert "analysis_package?.sql_result?.sql" not in script

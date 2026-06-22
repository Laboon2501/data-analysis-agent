"""Prompt language constraints for optional LLM nodes."""

from __future__ import annotations

from pathlib import Path


def test_llm_prompts_require_chinese_user_facing_text() -> None:
    """LLM prompts should keep schema keys English while natural language is Chinese."""

    prompt_paths = [
        Path("prompts/insight_writer.md"),
        Path("prompts/analysis_planner.md"),
        Path("prompts/sql_drafter.md"),
    ]

    for path in prompt_paths:
        text = path.read_text(encoding="utf-8")
        assert "JSON" in text
        assert "Chinese" in text or "中文" in text
        assert "table names" in text or "字段名" in text or "field names" in text


def test_sql_drafter_prompt_keeps_sql_identifiers_untranslated() -> None:
    """SQL prompt must not ask the model to translate physical identifiers."""

    text = Path("prompts/sql_drafter.md").read_text(encoding="utf-8")

    assert "must not be translated" in text
    assert "used_tables" in text
    assert "used_fields" in text

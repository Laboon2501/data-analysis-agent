"""Prompt contract tests for the optional context compactor."""

from pathlib import Path


def test_context_compactor_prompt_is_narrow_and_safe() -> None:
    """Context compactor prompt should forbid secrets and large payloads."""

    prompt = Path("prompts/context_compactor.md").read_text(encoding="utf-8")

    assert "AgentContextSummary" in prompt
    assert "Return exactly one JSON object" in prompt
    assert "Do not include full chat history" in prompt
    assert "API keys" in prompt
    assert "artifact body" in prompt

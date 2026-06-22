"""Tests for markdown prompt loading."""

import pytest

from llm import LLMAdapterError, LLMErrorCode, PromptLoader


def test_prompt_loader_loads_default_prompt_by_name() -> None:
    """Default loader should load prompts from the repository prompts directory."""

    prompt = PromptLoader().load("router")

    assert "# Router" in prompt
    assert "Return only JSON" in prompt


def test_prompt_loader_accepts_md_suffix(tmp_path) -> None:
    """Prompt names may include the .md suffix."""

    prompt_file = tmp_path / "custom.md"
    prompt_file.write_text("# Custom\n", encoding="utf-8")

    prompt = PromptLoader(tmp_path).load("custom.md")

    assert prompt == "# Custom\n"


def test_prompt_loader_rejects_path_traversal(tmp_path) -> None:
    """Prompt names should not escape the configured prompt directory."""

    loader = PromptLoader(tmp_path)

    with pytest.raises(LLMAdapterError) as error_info:
        loader.load("../outside")

    assert error_info.value.detail.code is LLMErrorCode.PROMPT_NAME_INVALID


def test_prompt_loader_raises_structured_error_for_missing_prompt(tmp_path) -> None:
    """Missing prompts should fail with a structured prompt-not-found error."""

    loader = PromptLoader(tmp_path)

    with pytest.raises(LLMAdapterError) as error_info:
        loader.load("missing")

    assert error_info.value.detail.code is LLMErrorCode.PROMPT_NOT_FOUND

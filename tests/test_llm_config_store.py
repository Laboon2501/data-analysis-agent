"""Persistent local LLM config store tests."""

from __future__ import annotations

import json

from app.llm_config_store import FileLLMConfigStore, StoredLLMConfig


def test_llm_config_store_saves_local_secret_but_returns_sanitized_view(tmp_path) -> None:
    """The local file may contain the key, but public views must not."""

    store = FileLLMConfigStore(tmp_path / "llm_config.json")
    saved = store.save(
        StoredLLMConfig(
            provider="deepseek",
            model="deepseek-chat",
            base_url="https://api.deepseek.com/v1",
            api_key="test-phase48-secret",
            enabled_nodes=["planner", "planner", "sql_drafter"],
        )
    )

    public = store.public_config()
    raw_file = json.loads((tmp_path / "llm_config.json").read_text(encoding="utf-8"))
    public_json = public.model_dump_json()

    assert saved.enabled_nodes == ["planner", "sql_drafter"]
    assert raw_file["api_key"] == "test-phase48-secret"
    assert public.api_key_configured is True
    assert public.base_url_host == "api.deepseek.com"
    assert "test-phase48-secret" not in public_json
    assert '"api_key":' not in public_json


def test_llm_config_store_rejects_unknown_node(tmp_path) -> None:
    """Only the narrow allowed LLM nodes can be persisted."""

    store = FileLLMConfigStore(tmp_path / "llm_config.json")

    try:
        store.save(
            StoredLLMConfig(
                provider="openai_compatible",
                model="model",
                api_key="test-api-key",
                enabled_nodes=["all_tools"],
            )
        )
    except ValueError as exc:
        assert "Unsupported LLM node" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Expected unsupported node to fail.")

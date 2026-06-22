"""Tests for LLM model configuration and harness construction."""

import pytest
from pydantic import ValidationError

import app.harness as harness
from llm import FakeLLMClient, ModelConfig
from schemas import AgentCommand, AgentIntent


def test_model_config_defaults_and_overrides() -> None:
    """ModelConfig should hold provider settings without secrets."""

    config = ModelConfig(
        model="gpt-test",
        base_url="https://llm.example/v1",
        api_key_env="TEST_LLM_KEY",
        max_retries=3,
        temperature=0.2,
        max_tokens=1024,
    )

    assert config.provider == "openai_compatible"
    assert config.model == "gpt-test"
    assert config.base_url == "https://llm.example/v1"
    assert config.api_key_env == "TEST_LLM_KEY"
    assert config.timeout_seconds == 30
    assert config.max_retries == 3
    assert config.temperature == 0.2
    assert config.max_tokens == 1024


@pytest.mark.parametrize(
    "field,value",
    [
        ("timeout_seconds", 0),
        ("max_retries", -1),
        ("temperature", -0.1),
        ("temperature", 2.1),
        ("max_tokens", 0),
    ],
)
def test_model_config_validates_runtime_bounds(field: str, value: object) -> None:
    """Invalid runtime settings should be rejected before provider use."""

    with pytest.raises(ValidationError):
        ModelConfig(model="gpt-test", **{field: value})


def test_harness_does_not_construct_real_client_for_rule_strategy(monkeypatch) -> None:
    """Default rule routing should ignore ModelConfig and avoid real provider setup."""

    def fail_if_called(config: ModelConfig):  # pragma: no cover - fails test if used.
        raise AssertionError(f"Should not construct provider for {config.model}")

    monkeypatch.setattr(harness, "OpenAICompatibleClient", fail_if_called)

    state = harness.build_initial_state(
        session_id="session-1",
        user_message="What is total revenue?",
        model_config=ModelConfig(model="gpt-test"),
    )

    assert state.command is AgentCommand.ANALYZE
    assert state.intent is AgentIntent.DIRECT_ANALYSIS


def test_harness_can_construct_client_from_model_config(monkeypatch) -> None:
    """Explicit LLM routing can build a provider client from ModelConfig."""

    fake_client = FakeLLMClient(['{"command": "report", "intent": "report_export"}'])
    captured_configs: list[ModelConfig] = []

    def fake_factory(config: ModelConfig):
        captured_configs.append(config)
        return fake_client

    monkeypatch.setattr(harness, "OpenAICompatibleClient", fake_factory)

    state = harness.build_initial_state(
        session_id="session-1",
        user_message="Make a leadership artifact",
        route_strategy="llm",
        model_config=ModelConfig(model="gpt-test", api_key_env="NOT_USED_IN_FAKE"),
    )

    assert state.command is AgentCommand.REPORT
    assert state.intent is AgentIntent.REPORT_EXPORT
    assert captured_configs[0].model == "gpt-test"
    assert len(fake_client.calls) == 1

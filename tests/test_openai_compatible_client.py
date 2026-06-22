"""Tests for the OpenAI-compatible client without real network calls."""

import pytest

from llm import LLMAdapterError, LLMErrorCode, LLMMessage, ModelConfig, OpenAICompatibleClient


def _provider_success(content: str = '{"ok": true}') -> dict:
    """Return a minimal OpenAI-compatible response payload."""

    return {
        "id": "chatcmpl-test",
        "model": "provider-model",
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 4},
    }


def test_openai_compatible_client_sends_payload_and_returns_response(monkeypatch) -> None:
    """The client should read env key, call base_url, and map provider response."""

    monkeypatch.setenv("TEST_LLM_KEY", "secret-value")
    captured: dict[str, object] = {}

    def transport(url, payload, headers, timeout_seconds):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        captured["timeout_seconds"] = timeout_seconds
        return _provider_success()

    client = OpenAICompatibleClient(
        ModelConfig(
            model="configured-model",
            base_url="https://llm.example/v1/",
            api_key_env="TEST_LLM_KEY",
            timeout_seconds=12,
            temperature=0.4,
            max_tokens=256,
        ),
        transport=transport,
    )

    response = client.complete(
        [LLMMessage(role="user", content="hello")],
        model="override-model",
        temperature=0.1,
        timeout_seconds=5,
    )

    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-value"
    assert captured["payload"]["model"] == "override-model"
    assert captured["payload"]["temperature"] == 0.1
    assert captured["payload"]["max_tokens"] == 256
    assert captured["payload"]["stream"] is False
    assert captured["timeout_seconds"] == 5
    assert response.content == '{"ok": true}'
    assert response.model == "provider-model"
    assert response.usage == {"prompt_tokens": 3, "completion_tokens": 4}
    assert response.metadata["provider"] == "openai_compatible"
    assert response.metadata["finish_reason"] == "stop"


def test_openai_compatible_client_requires_api_key(monkeypatch) -> None:
    """Missing API key env vars should fail before any transport call."""

    monkeypatch.delenv("MISSING_LLM_KEY", raising=False)
    called = False

    def transport(url, payload, headers, timeout_seconds):  # pragma: no cover
        nonlocal called
        called = True
        return _provider_success()

    client = OpenAICompatibleClient(
        ModelConfig(model="configured-model", api_key_env="MISSING_LLM_KEY"),
        transport=transport,
    )

    with pytest.raises(LLMAdapterError) as error_info:
        client.complete([LLMMessage(role="user", content="hello")])

    assert error_info.value.detail.code is LLMErrorCode.API_KEY_MISSING
    assert called is False


def test_openai_compatible_client_retries_transport_failures(monkeypatch) -> None:
    """Transient transport failures should be retried up to max_retries."""

    monkeypatch.setenv("TEST_LLM_KEY", "secret-value")
    attempts = 0

    def transport(url, payload, headers, timeout_seconds):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary failure")
        return _provider_success()

    client = OpenAICompatibleClient(
        ModelConfig(model="configured-model", api_key_env="TEST_LLM_KEY", max_retries=1),
        transport=transport,
    )

    response = client.complete([LLMMessage(role="user", content="hello")])

    assert attempts == 2
    assert response.content == '{"ok": true}'


def test_openai_compatible_client_converts_provider_error(monkeypatch) -> None:
    """Provider error payloads should become structured adapter errors."""

    monkeypatch.setenv("TEST_LLM_KEY", "secret-value")

    client = OpenAICompatibleClient(
        ModelConfig(model="configured-model", api_key_env="TEST_LLM_KEY"),
        transport=lambda *_: {"error": {"message": "bad request", "type": "invalid_request"}},
    )

    with pytest.raises(LLMAdapterError) as error_info:
        client.complete([LLMMessage(role="user", content="hello")])

    assert error_info.value.detail.code is LLMErrorCode.PROVIDER_ERROR
    assert error_info.value.detail.message == "bad request"


def test_openai_compatible_client_validates_provider_response(monkeypatch) -> None:
    """Malformed provider responses should fail with structured detail."""

    monkeypatch.setenv("TEST_LLM_KEY", "secret-value")
    client = OpenAICompatibleClient(
        ModelConfig(model="configured-model", api_key_env="TEST_LLM_KEY"),
        transport=lambda *_: {"choices": []},
    )

    with pytest.raises(LLMAdapterError) as error_info:
        client.complete([LLMMessage(role="user", content="hello")])

    assert error_info.value.detail.code is LLMErrorCode.PROVIDER_RESPONSE_INVALID


def test_openai_compatible_client_reports_exhausted_retries(monkeypatch) -> None:
    """Exhausted transport retries should become a request_failed error."""

    monkeypatch.setenv("TEST_LLM_KEY", "secret-value")
    attempts = 0

    def transport(url, payload, headers, timeout_seconds):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("still down")

    client = OpenAICompatibleClient(
        ModelConfig(model="configured-model", api_key_env="TEST_LLM_KEY", max_retries=2),
        transport=transport,
    )

    with pytest.raises(LLMAdapterError) as error_info:
        client.complete([LLMMessage(role="user", content="hello")])

    assert attempts == 3
    assert error_info.value.detail.code is LLMErrorCode.REQUEST_FAILED

"""Tests for the LLM adapter contracts and fake client."""

import pytest

from llm import FakeLLMClient, LLMAdapterError, LLMErrorCode, LLMMessage, LLMResponse


def test_fake_llm_client_returns_queued_response_and_records_messages() -> None:
    """FakeLLMClient should return deterministic responses and record calls."""

    client = FakeLLMClient(
        [
            LLMResponse(
                content='{"ok": true}',
                model="fake-model",
                usage={"tokens": 3},
            )
        ]
    )

    response = client.complete(
        [LLMMessage(role="user", content="hello")],
        model="ignored-real-model",
        temperature=0,
    )

    assert response.content == '{"ok": true}'
    assert response.model == "fake-model"
    assert response.usage == {"tokens": 3}
    assert len(client.calls) == 1
    assert client.calls[0][0].content == "hello"


def test_fake_llm_client_accepts_string_responses_added_later() -> None:
    """String responses should be normalized into LLMResponse objects."""

    client = FakeLLMClient()
    client.add_response('{"intent": "direct_analysis"}')

    response = client.complete([LLMMessage(role="user", content="route")])

    assert isinstance(response, LLMResponse)
    assert response.content == '{"intent": "direct_analysis"}'


def test_fake_llm_client_raises_structured_error_when_queue_is_empty() -> None:
    """Empty fake response queues should fail loudly with structured detail."""

    client = FakeLLMClient()

    with pytest.raises(LLMAdapterError) as error_info:
        client.complete([LLMMessage(role="user", content="hello")])

    assert error_info.value.detail.code is LLMErrorCode.FAKE_RESPONSE_EXHAUSTED
    assert error_info.value.detail.retryable is False

"""Fake LLM client for deterministic strategy tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from llm.base import LLMClient, LLMMessage, LLMResponse
from llm.errors import LLMAdapterError, LLMErrorCode, LLMErrorDetail


class FakeLLMClient(LLMClient):
    """Queue-backed fake client that records calls and returns controlled responses."""

    def __init__(self, responses: Iterable[LLMResponse | str] = ()) -> None:
        self._responses: deque[LLMResponse] = deque(
            response if isinstance(response, LLMResponse) else LLMResponse(content=response)
            for response in responses
        )
        self.calls: list[list[LLMMessage]] = []

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
    ) -> LLMResponse:
        """Record the call and return the next queued response."""

        self.calls.append([message.model_copy(deep=True) for message in messages])
        if not self._responses:
            raise LLMAdapterError(
                LLMErrorDetail(
                    code=LLMErrorCode.FAKE_RESPONSE_EXHAUSTED,
                    message="FakeLLMClient has no queued response.",
                    details={
                        "model": model,
                        "temperature": temperature,
                        "timeout_seconds": timeout_seconds,
                    },
                )
            )
        return self._responses.popleft().model_copy(deep=True)

    def add_response(self, response: LLMResponse | str) -> None:
        """Append a response to the fake queue."""

        queued_response = (
            response if isinstance(response, LLMResponse) else LLMResponse(content=response)
        )
        self._responses.append(queued_response)

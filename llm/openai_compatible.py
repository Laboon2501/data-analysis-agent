"""OpenAI-compatible non-streaming chat completion client."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from llm.base import LLMClient, LLMMessage, LLMResponse
from llm.config import ModelConfig
from llm.errors import LLMAdapterError, LLMErrorCode, LLMErrorDetail

ProviderTransport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


class OpenAICompatibleClient(LLMClient):
    """Minimal OpenAI-compatible chat completions client."""

    def __init__(
        self,
        config: ModelConfig,
        *,
        transport: ProviderTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport or _default_transport

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
    ) -> LLMResponse:
        """Call a non-streaming OpenAI-compatible chat completion endpoint."""

        api_key = self._api_key()
        active_model = model or self.config.model
        active_temperature = self.config.temperature if temperature is None else temperature
        active_timeout = timeout_seconds or self.config.timeout_seconds
        payload = {
            "model": active_model,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in messages
            ],
            "temperature": active_temperature,
            "stream": False,
        }
        if self.config.max_tokens is not None:
            payload["max_tokens"] = self.config.max_tokens

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        provider_response = self._send_with_retry(
            url=self._chat_completions_url(),
            payload=payload,
            headers=headers,
            timeout_seconds=active_timeout,
        )
        return self._parse_response(provider_response, fallback_model=active_model)

    def _api_key(self) -> str:
        """Read the provider API key from direct config or the configured env var."""

        api_key = self.config.api_key or os.getenv(self.config.api_key_env)
        if not api_key:
            raise LLMAdapterError(
                LLMErrorDetail(
                    code=LLMErrorCode.API_KEY_MISSING,
                    message=(
                        f"LLM API key environment variable is not set: {self.config.api_key_env}"
                    ),
                    details={"api_key_env": self.config.api_key_env},
                )
            )
        return api_key

    def _send_with_retry(
        self,
        *,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        """Send a request with bounded retries for transient transport failures."""

        max_attempts = self.config.max_retries + 1
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = self._transport(url, payload, headers, timeout_seconds)
                self._raise_for_provider_error(response)
                return response
            except LLMAdapterError as exc:
                last_error = exc
                if attempt >= max_attempts or not exc.detail.retryable:
                    raise
            except Exception as exc:
                last_error = exc
                if attempt >= max_attempts:
                    break
        raise LLMAdapterError(
            LLMErrorDetail(
                code=LLMErrorCode.REQUEST_FAILED,
                message="LLM provider request failed after retries.",
                retryable=False,
                details={
                    "attempts": max_attempts,
                    "error": str(last_error),
                    "provider": self.config.provider,
                    "base_url": self.config.base_url,
                },
            )
        ) from last_error

    def _raise_for_provider_error(self, response: dict[str, Any]) -> None:
        """Convert provider error payloads into structured adapter errors."""

        provider_error = response.get("error")
        if provider_error is None:
            return
        message = (
            provider_error.get("message", "LLM provider returned an error.")
            if isinstance(provider_error, dict)
            else str(provider_error)
        )
        raise LLMAdapterError(
            LLMErrorDetail(
                code=LLMErrorCode.PROVIDER_ERROR,
                message=message,
                retryable=False,
                details={"provider_error": provider_error},
            )
        )

    def _parse_response(
        self,
        response: dict[str, Any],
        *,
        fallback_model: str,
    ) -> LLMResponse:
        """Parse an OpenAI-compatible chat completion response."""

        try:
            choices = response["choices"]
            first_choice = choices[0]
            content = first_choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMAdapterError(
                LLMErrorDetail(
                    code=LLMErrorCode.PROVIDER_RESPONSE_INVALID,
                    message="LLM provider response did not contain message content.",
                    details={"response": response},
                )
            ) from exc

        if not isinstance(content, str):
            raise LLMAdapterError(
                LLMErrorDetail(
                    code=LLMErrorCode.PROVIDER_RESPONSE_INVALID,
                    message="LLM provider message content must be a string.",
                    details={"response": response},
                )
            )

        return LLMResponse(
            content=content,
            model=response.get("model") or fallback_model,
            usage=response.get("usage") or {},
            metadata={
                "provider": self.config.provider,
                "id": response.get("id"),
                "finish_reason": first_choice.get("finish_reason"),
            },
        )

    def _chat_completions_url(self) -> str:
        """Return the OpenAI-compatible chat completions URL."""

        return f"{self.config.base_url.rstrip('/')}/chat/completions"


def _default_transport(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Send one JSON request using the Python standard library."""

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            response_payload = response.read().decode("utf-8")
    except HTTPError as exc:
        raise _http_error(exc) from exc
    except URLError as exc:
        raise _transport_error(exc) from exc

    try:
        parsed = json.loads(response_payload)
    except json.JSONDecodeError as exc:
        raise LLMAdapterError(
            LLMErrorDetail(
                code=LLMErrorCode.PROVIDER_RESPONSE_INVALID,
                message="LLM provider returned non-JSON response.",
                details={"response": response_payload},
            )
        ) from exc
    if not isinstance(parsed, dict):
        raise LLMAdapterError(
            LLMErrorDetail(
                code=LLMErrorCode.PROVIDER_RESPONSE_INVALID,
                message="LLM provider response JSON must be an object.",
                details={"response": parsed},
            )
        )
    return parsed


def _http_error(exc: HTTPError) -> LLMAdapterError:
    """Convert HTTP errors into provider errors."""

    try:
        body = exc.read().decode("utf-8")
        parsed_body = json.loads(body) if body else {}
    except Exception:
        parsed_body = {"message": str(exc)}
    return LLMAdapterError(
        LLMErrorDetail(
            code=LLMErrorCode.PROVIDER_ERROR,
            message=f"LLM provider returned HTTP {exc.code}.",
            retryable=exc.code >= 500,
            details={"status_code": exc.code, "body": parsed_body},
        )
    )


def _transport_error(exc: URLError) -> LLMAdapterError:
    """Convert transport errors into retryable request failures."""

    return LLMAdapterError(
        LLMErrorDetail(
            code=LLMErrorCode.REQUEST_FAILED,
            message="LLM provider transport failed.",
            retryable=True,
            details={"error": str(exc)},
        )
    )

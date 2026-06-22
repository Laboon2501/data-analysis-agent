"""Structured LLM adapter error contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from schemas._base import StrictBaseModel


class LLMErrorCode(StrEnum):
    """Stable error codes for adapter and strategy failures."""

    CLIENT_UNAVAILABLE = "client_unavailable"
    RESPONSE_PARSE_ERROR = "response_parse_error"
    JSON_INVALID = "json_invalid"
    PROMPT_NOT_FOUND = "prompt_not_found"
    PROMPT_NAME_INVALID = "prompt_name_invalid"
    FAKE_RESPONSE_EXHAUSTED = "fake_response_exhausted"
    API_KEY_MISSING = "api_key_missing"
    REQUEST_FAILED = "request_failed"
    PROVIDER_ERROR = "provider_error"
    PROVIDER_RESPONSE_INVALID = "provider_response_invalid"


class LLMErrorDetail(StrictBaseModel):
    """Serializable LLM error detail that can be copied into AgentState later."""

    code: LLMErrorCode
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class LLMAdapterError(RuntimeError):
    """Base exception carrying structured LLM error details."""

    def __init__(self, detail: LLMErrorDetail) -> None:
        super().__init__(detail.message)
        self.detail = detail

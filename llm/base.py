"""Shared LLM adapter protocols and message schemas."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import Field

from schemas._base import StrictBaseModel


class LLMMessage(StrictBaseModel):
    """Single chat-style message sent to an LLM provider adapter."""

    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(StrictBaseModel):
    """Provider-independent LLM response used by graph nodes."""

    content: str
    model: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMClient(Protocol):
    """Minimal non-streaming LLM client contract for node strategy switching."""

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
    ) -> LLMResponse:
        """Return one complete response for the provided messages."""

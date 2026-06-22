"""Configuration models for real LLM provider adapters."""

from __future__ import annotations

from pydantic import Field

from schemas._base import StrictBaseModel


class ModelConfig(StrictBaseModel):
    """Provider/model configuration without embedding secrets in code."""

    provider: str = "openai_compatible"
    model: str
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    api_key: str | None = Field(default=None, repr=False, exclude=True)
    timeout_seconds: float = Field(default=30, gt=0)
    max_retries: int = Field(default=2, ge=0)
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)

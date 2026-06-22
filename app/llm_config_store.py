"""Persistent local LLM configuration store for the product Web UI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import Field

from app.llm_runtime import ALLOWED_LLM_NODE_ALIASES, DEFAULT_REAL_LLM_API_KEY_ENV
from llm.config import ModelConfig
from schemas._base import StrictBaseModel, utc_now

DEFAULT_LLM_CONFIG_PATH = "runtime/llm_config.json"
DEFAULT_PROVIDER_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "openai_compatible": "https://api.openai.com/v1",
}


class LLMProviderName(StrEnum):
    """Provider choices exposed by the Web UI."""

    DEEPSEEK = "deepseek"
    OPENAI_COMPATIBLE = "openai_compatible"
    OPENAI = "openai"
    CUSTOM = "custom"


class StoredLLMConfig(StrictBaseModel):
    """Backend-only persisted LLM config; api_key is never returned directly."""

    provider: LLMProviderName = LLMProviderName.OPENAI_COMPATIBLE
    model: str = ""
    base_url: str | None = None
    api_key: str | None = Field(default=None, repr=False, exclude=True)
    api_key_secret_ref: str | None = None
    enabled_nodes: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class PublicLLMConfig(StrictBaseModel):
    """Sanitized LLM config returned to frontend clients."""

    provider: LLMProviderName = LLMProviderName.OPENAI_COMPATIBLE
    model: str | None = None
    base_url_host: str | None = None
    base_url_masked: str | None = None
    api_key_configured: bool = False
    api_key_secret_ref: str | None = None
    enabled_nodes: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class LLMConnectionTestResult(StrictBaseModel):
    """Safe result for POST /llm/test."""

    ok: bool
    provider: str | None = None
    model: str | None = None
    base_url_host: str | None = None
    message: str
    error_type: str | None = None


@dataclass
class FileLLMConfigStore:
    """Small JSON-backed store for local technical-preview LLM config."""

    path: Path | str = DEFAULT_LLM_CONFIG_PATH

    def __post_init__(self) -> None:
        self.path = Path(self.path).expanduser()

    def load(self) -> StoredLLMConfig | None:
        """Load the stored config, returning None when no file exists."""

        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("LLM config file must contain a JSON object.")
        return StoredLLMConfig.model_validate(data)

    def save(self, config: StoredLLMConfig) -> StoredLLMConfig:
        """Persist one config object to disk."""

        normalized = normalize_stored_llm_config(config)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = normalized.model_dump(mode="json")
        if normalized.api_key:
            payload["api_key"] = normalized.api_key
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return normalized

    def public_config(self) -> PublicLLMConfig:
        """Return the stored config with secrets removed."""

        return public_llm_config(self.load())


class NullLLMConfigStore:
    """No-op store used when a backend does not support persisted LLM config."""

    def load(self) -> StoredLLMConfig | None:
        return None

    def save(self, config: StoredLLMConfig) -> StoredLLMConfig:
        return normalize_stored_llm_config(config)

    def public_config(self) -> PublicLLMConfig:
        return PublicLLMConfig()


def normalize_stored_llm_config(config: StoredLLMConfig) -> StoredLLMConfig:
    """Validate provider fields and dedupe enabled node aliases."""

    provider = LLMProviderName(config.provider)
    base_url = config.base_url or DEFAULT_PROVIDER_BASE_URLS.get(provider.value)
    if provider is LLMProviderName.CUSTOM and not base_url:
        raise ValueError("custom LLM provider requires base_url.")
    enabled_nodes = _normalize_enabled_nodes(config.enabled_nodes)
    return config.model_copy(
        update={
            "provider": provider,
            "model": config.model.strip(),
            "base_url": base_url.rstrip("/") if base_url else None,
            "api_key": config.api_key.strip() if config.api_key else None,
            "api_key_secret_ref": config.api_key_secret_ref or _secret_ref_for(provider),
            "enabled_nodes": enabled_nodes,
            "updated_at": utc_now(),
        },
        deep=True,
    )


def public_llm_config(config: StoredLLMConfig | None) -> PublicLLMConfig:
    """Build a sanitized frontend-facing config."""

    if config is None:
        return PublicLLMConfig()
    normalized = normalize_stored_llm_config(config)
    base_url = normalized.base_url or ""
    return PublicLLMConfig(
        provider=normalized.provider,
        model=normalized.model or None,
        base_url_host=_base_url_host(base_url),
        base_url_masked=_base_url_masked(base_url) if base_url else None,
        api_key_configured=bool(normalized.api_key),
        api_key_secret_ref=normalized.api_key_secret_ref,
        enabled_nodes=normalized.enabled_nodes,
        updated_at=normalized.updated_at,
    )


def model_config_from_stored_llm_config(config: StoredLLMConfig) -> ModelConfig:
    """Convert a stored Web UI config into the existing provider model config."""

    normalized = normalize_stored_llm_config(config)
    if not normalized.model:
        raise ValueError("LLM config requires model.")
    if not normalized.api_key:
        raise ValueError("LLM config requires API key.")
    return ModelConfig(
        provider=normalized.provider.value,
        model=normalized.model,
        base_url=normalized.base_url or DEFAULT_PROVIDER_BASE_URLS["openai_compatible"],
        api_key_env=DEFAULT_REAL_LLM_API_KEY_ENV,
        api_key=normalized.api_key,
    )


def app_config_updates_from_stored_llm_config(config: StoredLLMConfig | None) -> dict[str, Any]:
    """Return AppConfig updates for a stored LLM config."""

    if config is None:
        return {}
    normalized = normalize_stored_llm_config(config)
    return {
        "llm_provider": normalized.provider.value,
        "llm_model": normalized.model or None,
        "llm_base_url": normalized.base_url,
        "llm_api_key": normalized.api_key,
        "llm_enabled_nodes": normalized.enabled_nodes,
    }


def _normalize_enabled_nodes(enabled_nodes: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized_nodes: list[str] = []
    for node_name in enabled_nodes:
        normalized = str(node_name).strip()
        if not normalized:
            continue
        if normalized not in ALLOWED_LLM_NODE_ALIASES:
            raise ValueError(f"Unsupported LLM node: {node_name}")
        if normalized not in seen:
            normalized_nodes.append(normalized)
            seen.add(normalized)
    return normalized_nodes


def _secret_ref_for(provider: LLMProviderName) -> str:
    return f"local_file:{provider.value}:api_key"


def _base_url_host(base_url: str) -> str | None:
    parsed = urlparse(base_url)
    return parsed.netloc or parsed.path or None


def _base_url_masked(base_url: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.netloc:
        return base_url
    host = parsed.hostname or parsed.netloc
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return parsed._replace(netloc=host).geturl()


__all__ = [
    "DEFAULT_LLM_CONFIG_PATH",
    "FileLLMConfigStore",
    "LLMConnectionTestResult",
    "LLMProviderName",
    "NullLLMConfigStore",
    "PublicLLMConfig",
    "StoredLLMConfig",
    "app_config_updates_from_stored_llm_config",
    "model_config_from_stored_llm_config",
    "normalize_stored_llm_config",
    "public_llm_config",
]

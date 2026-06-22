"""Redis-backed CacheStore implementation."""

from __future__ import annotations

import os
from typing import Any

from persistence.serialization import deserialize_value, serialize_value

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
REDIS_URL_ENV = "DATA_ANALYSIS_AGENT_REDIS_URL"
REDIS_PREFIX_ENV = "DATA_ANALYSIS_AGENT_REDIS_PREFIX"


class RedisCacheStore:
    """CacheStore backed by Redis string values with optional TTL."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        url: str | None = None,
        key_prefix: str | None = None,
    ) -> None:
        self.client = client or _build_redis_client(url or _redis_url_from_env())
        self.key_prefix = key_prefix if key_prefix is not None else _redis_prefix_from_env("cache")

    @classmethod
    def from_env(cls) -> RedisCacheStore:
        """Build a Redis cache store using environment configuration."""

        return cls()

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        """Store a value under a namespaced key with optional TTL."""

        payload = serialize_value(value)
        full_key = self._key(key)
        if ttl_seconds is None:
            self.client.set(full_key, payload)
            return
        ttl_ms = max(1, int(ttl_seconds * 1000))
        self.client.set(full_key, payload, px=ttl_ms)

    def get(self, key: str) -> Any | None:
        """Return a cached value when present."""

        payload = self.client.get(self._key(key))
        if payload is None:
            return None
        return deserialize_value(payload)

    def delete(self, key: str) -> None:
        """Remove a cached value."""

        self.client.delete(self._key(key))

    def _key(self, key: str) -> str:
        """Return a Redis key scoped to this cache store."""

        return f"{self.key_prefix}{key}"


def _redis_url_from_env() -> str:
    """Return Redis URL from project-specific or common environment variables."""

    return os.getenv(REDIS_URL_ENV) or os.getenv("REDIS_URL") or DEFAULT_REDIS_URL


def _redis_prefix_from_env(namespace: str) -> str:
    """Return a stable Redis key prefix."""

    base_prefix = os.getenv(REDIS_PREFIX_ENV, "daa")
    return f"{base_prefix}:{namespace}:"


def _build_redis_client(url: str) -> Any:
    """Create a redis-py client lazily so tests do not require Redis."""

    try:
        import redis
    except ImportError as exc:  # pragma: no cover - exercised only without redis-py installed.
        raise RuntimeError(
            "RedisCacheStore requires the optional 'redis' package when no client is injected."
        ) from exc
    return redis.Redis.from_url(url)

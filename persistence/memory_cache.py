"""In-memory cache store for profile and session hot-state tests."""

from __future__ import annotations

from copy import deepcopy
from time import time
from typing import Any


class InMemoryCacheStore:
    """Process-local cache with optional TTL support."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[Any, float | None]] = {}

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        """Store a value with optional TTL seconds."""

        expires_at = None if ttl_seconds is None else time() + ttl_seconds
        self._values[key] = (deepcopy(value), expires_at)

    def get(self, key: str) -> Any | None:
        """Return a deep copy of the cached value when present and unexpired."""

        entry = self._values.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and expires_at <= time():
            self.delete(key)
            return None
        return deepcopy(value)

    def delete(self, key: str) -> None:
        """Remove a value from the cache."""

        self._values.pop(key, None)

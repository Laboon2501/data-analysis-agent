"""Redis-backed EventStore implementation."""

from __future__ import annotations

import os
from collections.abc import Iterator
from time import monotonic, sleep
from typing import Any

from schemas.event import AgentEvent, EventType

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
REDIS_URL_ENV = "DATA_ANALYSIS_AGENT_REDIS_URL"
REDIS_PREFIX_ENV = "DATA_ANALYSIS_AGENT_REDIS_PREFIX"
LARGE_ARTIFACT_KEYS = frozenset(
    {
        "chart_html",
        "html",
        "file_content",
        "file_bytes",
        "binary",
        "data_url",
    }
)
TERMINAL_EVENT_TYPES = frozenset(
    {
        EventType.DONE,
        EventType.ERROR,
        EventType.STOPPED,
    }
)


class RedisEventStore:
    """EventStore backed by Redis lists with a stream-compatible iterator."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        url: str | None = None,
        key_prefix: str | None = None,
    ) -> None:
        self.client = client or _build_redis_client(url or _redis_url_from_env())
        self.key_prefix = key_prefix if key_prefix is not None else _redis_prefix_from_env("events")

    @classmethod
    def from_env(cls) -> RedisEventStore:
        """Build a Redis event store using environment configuration."""

        return cls()

    def append_event(self, event: AgentEvent) -> None:
        """Append a sanitized structured event."""

        sanitized_event = _sanitize_event(event)
        payload = sanitized_event.model_dump_json()
        self.client.rpush(self._events_key(), payload)

    def list_events(
        self, session_id: str | None = None, job_id: str | None = None
    ) -> list[AgentEvent]:
        """List events, optionally filtered by session and job."""

        events = [
            self._decode_event(payload) for payload in self.client.lrange(self._events_key(), 0, -1)
        ]
        return [
            event
            for event in events
            if (session_id is None or event.session_id == session_id)
            and (job_id is None or event.job_id == job_id)
        ]

    def stream_events(
        self,
        *,
        session_id: str | None = None,
        job_id: str | None = None,
        start_index: int = 0,
        poll_interval_seconds: float = 0.1,
        timeout_seconds: float | None = 30.0,
        block: bool = True,
    ) -> Iterator[AgentEvent]:
        """Poll Redis for events and stop at terminal job events or timeout."""

        deadline = None if timeout_seconds is None else monotonic() + timeout_seconds
        next_index = start_index
        while True:
            matching_events = self.list_events(session_id=session_id, job_id=job_id)
            while next_index < len(matching_events):
                event = matching_events[next_index]
                next_index += 1
                yield event
                if event.event_type in TERMINAL_EVENT_TYPES:
                    return

            if not block:
                return
            if deadline is not None and monotonic() >= deadline:
                return
            sleep(max(0.01, poll_interval_seconds))

    def _events_key(self) -> str:
        """Return the Redis list key for append-only events."""

        return f"{self.key_prefix}all"

    @staticmethod
    def _decode_event(payload: bytes | str) -> AgentEvent:
        """Decode one Redis list entry into AgentEvent."""

        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        return AgentEvent.model_validate_json(text)


def _sanitize_event(event: AgentEvent) -> AgentEvent:
    """Return an event copy without large inline artifact content."""

    return event.model_copy(update={"payload": _sanitize_payload(event.payload)}, deep=True)


def _sanitize_payload(payload: Any) -> Any:
    """Remove known large artifact fields from Redis event payloads."""

    if isinstance(payload, dict):
        return {
            key: "<omitted>" if key in LARGE_ARTIFACT_KEYS else _sanitize_payload(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_sanitize_payload(item) for item in payload]
    return payload


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
            "RedisEventStore requires the optional 'redis' package when no client is injected."
        ) from exc
    return redis.Redis.from_url(url)

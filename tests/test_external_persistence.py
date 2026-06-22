"""Tests for Redis/Postgres/File persistence skeletons without external services."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from persistence import (
    FileArtifactStore,
    PostgresCheckpointStore,
    RedisCacheStore,
    RedisEventStore,
)
from schemas import AgentState, DatabaseProfile, EventType, ProfileStatus
from schemas.event import AgentEvent


class FakeRedis:
    """Tiny Redis-like fake for cache and event store unit tests."""

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.lists: dict[str, list[bytes]] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key: str, value: str, px: int | None = None) -> None:
        """Store a string value as Redis bytes and remember TTL milliseconds."""

        self.values[key] = value.encode("utf-8")
        if px is not None:
            self.ttls[key] = px

    def get(self, key: str) -> bytes | None:
        """Return a stored value."""

        return self.values.get(key)

    def delete(self, key: str) -> None:
        """Remove a stored value."""

        self.values.pop(key, None)

    def rpush(self, key: str, value: str) -> None:
        """Append a list entry."""

        self.lists.setdefault(key, []).append(value.encode("utf-8"))

    def lrange(self, key: str, start: int, end: int) -> list[bytes]:
        """Return a Redis-like inclusive range."""

        values = self.lists.get(key, [])
        stop = None if end == -1 else end + 1
        return values[start:stop]


class PollingFakeRedis(FakeRedis):
    """Redis fake that appends a terminal event after an initial empty poll."""

    def __init__(self, event: AgentEvent) -> None:
        super().__init__()
        self.event = event
        self.calls = 0

    def lrange(self, key: str, start: int, end: int) -> list[bytes]:
        """Append a terminal event on the second poll."""

        self.calls += 1
        if self.calls == 2:
            self.rpush(key, self.event.model_dump_json())
        return super().lrange(key, start, end)


def test_redis_cache_store_round_trips_plain_values_and_ttl() -> None:
    """Redis cache should set/get/delete values and pass TTL to Redis."""

    client = FakeRedis()
    store = RedisCacheStore(client=client, key_prefix="test:cache:")

    store.set("answer", {"value": 42}, ttl_seconds=1.5)

    assert store.get("answer") == {"value": 42}
    assert client.ttls["test:cache:answer"] == 1500
    store.delete("answer")
    assert store.get("answer") is None


def test_redis_cache_store_round_trips_pydantic_models() -> None:
    """Redis cache should preserve typed Pydantic models used by profile caching."""

    client = FakeRedis()
    store = RedisCacheStore(client=client, key_prefix="test:cache:")
    profile = DatabaseProfile(
        datasource_id="warehouse",
        schema_hash="hash-1",
        status=ProfileStatus.CONFIRMED,
    )

    store.set("profile", profile)

    cached_profile = store.get("profile")
    assert isinstance(cached_profile, DatabaseProfile)
    assert cached_profile.datasource_id == "warehouse"
    assert cached_profile.status is ProfileStatus.CONFIRMED


def test_redis_event_store_lists_filters_and_sanitizes_events() -> None:
    """Redis events should preserve order while omitting large artifact bodies."""

    client = FakeRedis()
    store = RedisEventStore(client=client, key_prefix="test:events:")
    first = AgentEvent(
        event_type=EventType.CHART_REF,
        session_id="session-1",
        job_id="job-1",
        payload={"artifact_ref": "artifact:chart-1", "chart_html": "<html>large</html>"},
    )
    second = AgentEvent(event_type=EventType.DONE, session_id="session-1", job_id="job-1")
    third = AgentEvent(event_type=EventType.DONE, session_id="session-1", job_id="job-2")

    store.append_event(first)
    store.append_event(second)
    store.append_event(third)

    job_events = store.list_events(session_id="session-1", job_id="job-1")
    assert [event.event_type for event in job_events] == [EventType.CHART_REF, EventType.DONE]
    assert job_events[0].payload["artifact_ref"] == "artifact:chart-1"
    assert job_events[0].payload["chart_html"] == "<omitted>"
    assert [event.event_type for event in store.stream_events(job_id="job-1")] == [
        EventType.CHART_REF,
        EventType.DONE,
    ]


def test_redis_event_store_poll_stream_waits_for_future_events() -> None:
    """Redis event stream should poll for future events without external Redis."""

    terminal_event = AgentEvent(
        event_type=EventType.DONE,
        session_id="session-1",
        job_id="job-1",
    )
    client = PollingFakeRedis(terminal_event)
    store = RedisEventStore(client=client, key_prefix="test:events:")

    streamed_events = list(
        store.stream_events(
            job_id="job-1",
            poll_interval_seconds=0.01,
            timeout_seconds=1,
        )
    )

    assert [event.event_type for event in streamed_events] == [EventType.DONE]
    assert client.calls >= 2


def test_postgres_checkpoint_store_saves_and_updates_state_with_sqlalchemy() -> None:
    """Checkpoint skeleton should work with an injected SQLAlchemy engine in tests."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    store = PostgresCheckpointStore(engine=engine, table_name="checkpoints")
    state = AgentState(session_id="session-1", job_id="job-1", user_message="hello")

    store.save_checkpoint(state, status="running")
    updated_state = state.model_copy(update={"final_response_text": "done"}, deep=True)
    store.save_checkpoint(updated_state, status="completed")

    loaded_state = store.load_checkpoint("session-1", "job-1")
    with engine.begin() as connection:
        row = connection.execute(select(store.table).where(store.table.c.job_id == "job-1")).first()

    assert loaded_state is not None
    assert loaded_state.final_response_text == "done"
    assert row is not None
    assert row.status == "completed"
    assert row.created_at is not None
    assert row.updated_at is not None
    assert store.load_checkpoint("missing", "job-1") is None


def test_file_artifact_store_persists_content_and_metadata(tmp_path) -> None:
    """File artifact store should return references without using chat history."""

    store = FileArtifactStore(root_dir=tmp_path)

    artifact_ref = store.save_artifact(
        {"rows": [{"value": 42}]},
        metadata={"kind": "query_result"},
    )
    record = store.get_artifact(artifact_ref)
    metadata_paths = list(tmp_path.glob("*.metadata.json"))

    assert artifact_ref.startswith("artifact:file:")
    assert record is not None
    assert record.content == {"rows": [{"value": 42}]}
    assert record.metadata == {"kind": "query_result"}
    artifact_id = artifact_ref.rsplit(":", maxsplit=1)[-1]
    metadata = store.get_artifact_metadata(artifact_id)
    assert metadata is not None
    assert metadata.artifact_ref == artifact_ref
    assert metadata.artifact_id == artifact_id
    assert metadata.metadata == {"kind": "query_result"}
    assert metadata.content_type == "json"
    assert store.get_artifact_content(artifact_id) == {"rows": [{"value": 42}]}
    assert len(metadata_paths) == 1
    metadata_payload = json.loads(metadata_paths[0].read_text(encoding="utf-8"))
    assert metadata_payload["artifact_ref"] == artifact_ref
    assert metadata_payload["metadata"] == {"kind": "query_result"}


def test_file_artifact_store_rejects_ref_path_traversal(tmp_path) -> None:
    """File artifact refs should not escape the configured root."""

    store = FileArtifactStore(root_dir=tmp_path)

    with pytest.raises(ValueError, match="Invalid artifact id"):
        store.get_artifact("artifact:file:../outside")

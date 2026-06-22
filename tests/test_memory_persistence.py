"""Tests for in-memory persistence implementations."""

from persistence import (
    InMemoryArtifactStore,
    InMemoryCacheStore,
    InMemoryCheckpointStore,
    InMemoryEventStore,
    InMemoryVectorMemoryStore,
)
from schemas import AgentEvent, AgentState, EventType, SimilarCase


def test_checkpoint_store_saves_and_loads_state_copies() -> None:
    """Checkpoint store should isolate saved state from later mutations."""

    store = InMemoryCheckpointStore()
    state = AgentState(session_id="session-1", job_id="job-1", user_message="question")

    store.save_checkpoint(state)
    state.user_message = "mutated"

    loaded = store.load_checkpoint("session-1", "job-1")

    assert loaded is not None
    assert loaded.user_message == "question"


def test_cache_store_get_delete_and_copy_behavior() -> None:
    """Cache store should return copies and support delete."""

    store = InMemoryCacheStore()
    value = {"items": [1]}

    store.set("profile", value)
    value["items"].append(2)
    cached = store.get("profile")
    cached["items"].append(3)

    assert store.get("profile") == {"items": [1]}
    store.delete("profile")
    assert store.get("profile") is None


def test_event_store_filters_by_session_and_job() -> None:
    """Event store should support session and job filtering."""

    store = InMemoryEventStore()
    first = AgentEvent(event_type=EventType.NODE_START, session_id="s1", job_id="j1")
    second = AgentEvent(event_type=EventType.NODE_END, session_id="s1", job_id="j2")
    store.append_event(first)
    store.append_event(second)

    assert [event.job_id for event in store.list_events(session_id="s1")] == ["j1", "j2"]
    assert [event.event_type for event in store.list_events(session_id="s1", job_id="j1")] == [
        EventType.NODE_START
    ]


def test_artifact_store_returns_opaque_reference_and_record() -> None:
    """Artifacts should be retrieved by reference instead of inline history content."""

    store = InMemoryArtifactStore()
    artifact_ref = store.save_artifact("chart-html", metadata={"kind": "chart"})

    record = store.get_artifact(artifact_ref)

    assert artifact_ref.startswith("artifact:")
    assert record is not None
    assert record.content == "chart-html"
    assert record.metadata == {"kind": "chart"}

    artifact_id = artifact_ref.rsplit(":", maxsplit=1)[-1]
    metadata = store.get_artifact_metadata(artifact_id)
    assert metadata is not None
    assert metadata.artifact_ref == artifact_ref
    assert metadata.artifact_id == artifact_id
    assert metadata.metadata == {"kind": "chart"}
    assert store.get_artifact_content(artifact_id) == "chart-html"


def test_vector_memory_store_orders_by_score_without_external_vector_logic() -> None:
    """The memory implementation should provide deterministic test retrieval."""

    store = InMemoryVectorMemoryStore()
    low_score_case = SimilarCase(user_question="low", score=0.1)
    high_score_case = SimilarCase(user_question="high", score=0.9)
    store.add_case(low_score_case)
    store.add_case(high_score_case)

    results = store.search_similar_cases("anything", limit=1)

    assert results == [high_score_case]

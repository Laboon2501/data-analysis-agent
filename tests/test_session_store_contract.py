"""Contract tests shared by session store implementations."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.llm_runtime import LLMRuntimeMode
from app.sessions import (
    ChatRole,
    InMemorySessionStore,
    SessionJobSummary,
    SessionStore,
    SQLAlchemySessionStore,
)
from schemas._base import utc_now


@pytest.mark.parametrize("store_factory", ["memory", "sqlite"])
def test_session_store_contract_create_message_settings_and_artifact(
    store_factory: str,
    tmp_path,
) -> None:
    """Both memory and SQLite stores should implement the same public contract."""

    store = _store_factory(store_factory, tmp_path)()

    created = store.create_session(session_id="contract-a", title="Contract")
    message = store.add_message(
        "contract-a",
        role=ChatRole.USER,
        content="hello",
        metadata={"source": "test"},
    )
    store.update_session_datasource("contract-a", "demo")
    store.update_session_llm_config(
        "contract-a",
        mode=LLMRuntimeMode.FAKE_LLM,
        enabled_nodes=["planner"],
    )
    store.add_artifact_ref("contract-a", "chart-1")
    record = store.get_session("contract-a")

    assert created.session_id == "contract-a"
    assert message.content == "hello"
    assert record is not None
    assert record.datasource_id == "demo"
    assert record.llm_mode is LLMRuntimeMode.FAKE_LLM
    assert record.enabled_llm_nodes == ["planner"]
    assert record.artifact_refs == ["artifact:chart-1"]
    assert store.list_messages("contract-a")[0].metadata == {"source": "test"}
    assert store.status().session_count == 1


@pytest.mark.parametrize("store_factory", ["memory", "sqlite"])
def test_session_store_contract_records_job_summary(store_factory: str, tmp_path) -> None:
    """Job summaries should be listed and merge artifact refs into session records."""

    store = _store_factory(store_factory, tmp_path)()
    now = utc_now()

    store.record_job(
        SessionJobSummary(
            job_id="job-1",
            session_id="contract-a",
            status="completed",
            intent="direct_analysis",
            command="analyze",
            created_at=now,
            updated_at=now,
            artifact_refs=["artifact:chart-1"],
        )
    )

    assert store.list_jobs("contract-a")[0].job_id == "job-1"
    assert store.get_session("contract-a").artifact_refs == ["artifact:chart-1"]


def _store_factory(kind: str, tmp_path) -> Callable[[], SessionStore]:
    if kind == "memory":
        return InMemorySessionStore
    db_path = tmp_path / "session-history.sqlite"
    return lambda: SQLAlchemySessionStore(url=f"sqlite:///{db_path}")

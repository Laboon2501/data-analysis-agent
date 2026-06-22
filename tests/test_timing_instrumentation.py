"""Runtime timing instrumentation tests."""

from __future__ import annotations

from app.harness import build_initial_state
from app.workers import InMemoryJobRunner, JobStatus
from llm import FakeLLMClient
from llm.base import LLMResponse
from schemas.event import EventType


def test_node_timing_records_and_events_include_duration(sqlite_data_source) -> None:
    """Node runtime should expose small duration metadata for developer diagnostics."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    state = build_initial_state(
        session_id="timing",
        user_message="What is total revenue?",
        datasource_id=sqlite_data_source.datasource_id,
    )

    job = runner.submit_job(state)

    assert job.status is JobStatus.COMPLETED
    assert job.final_state is not None
    records = job.final_state.timing_records
    assert records
    assert all(record.duration_ms is not None for record in records)
    assert {record.node_name for record in records} >= {"interpret_question", "execute_sql"}

    node_end_events = [
        event for event in runner.list_events(job.job_id) if event.event_type is EventType.NODE_END
    ]
    assert any(event.payload.get("duration_ms") is not None for event in node_end_events)
    execute_events = [event for event in node_end_events if event.node_name == "execute_sql"]
    assert execute_events
    assert execute_events[-1].payload["row_count"] == job.final_state.sql_result.row_count


def test_llm_end_event_includes_duration_without_secret(sqlite_data_source) -> None:
    """LLM timing metadata should be bounded and secret-free."""

    client = FakeLLMClient(
        [
            LLMResponse(
                content=(
                    '{"title": "模型洞察", "summary": "汇总结果为 310。", '
                    '"evidence": ["row_count=1"], "confidence": 0.8}'
                ),
                model="fake-model",
                metadata={"provider": "fake", "api_key": "test-secret-value"},
            )
        ]
    )
    runner = InMemoryJobRunner(
        data_source=sqlite_data_source,
        llm_client=client,
        node_strategies={"generate_insight": "llm"},
    )
    state = build_initial_state(
        session_id="timing-llm",
        user_message="What is total revenue?",
        datasource_id=sqlite_data_source.datasource_id,
    )

    job = runner.submit_job(state)

    assert job.status is JobStatus.COMPLETED
    llm_end_events = [
        event for event in runner.list_events(job.job_id) if event.event_type is EventType.LLM_END
    ]
    assert llm_end_events
    assert llm_end_events[-1].payload["duration_ms"] >= 0
    assert "test-secret-value" not in str(llm_end_events[-1].payload)

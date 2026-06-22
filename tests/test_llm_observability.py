"""Tests for structured LLM observability events and fallback diagnostics."""

from __future__ import annotations

import json

from app.harness import build_initial_state
from app.workers import InMemoryJobRunner, JobStatus
from llm import FakeLLMClient, LLMAdapterError, LLMErrorCode, LLMErrorDetail, LLMResponse
from llm.base import LLMMessage
from nodes.insight_nodes import generate_insight
from nodes.router import route
from schemas import AgentCommand, AgentIntent, AgentState, DirectQuestionKind, QueryResult
from schemas.direct_analysis import QuestionInterpretation
from schemas.event import EventType
from schemas.query_result import QueryColumn


class SecretFailingLLMClient:
    """Fake provider that raises an error containing credential-shaped text."""

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
    ) -> LLMResponse:
        """Raise a structured provider error with sensitive-looking diagnostics."""

        raise LLMAdapterError(
            LLMErrorDetail(
                code=LLMErrorCode.REQUEST_FAILED,
                message="provider failed with api_key=fake-secret",
                retryable=False,
                details={
                    "api_key": "fake-secret",
                    "authorization": "Bearer fake-secret",
                    "content": "fake-secret should not be copied as raw output",
                    "model": model,
                    "temperature": temperature,
                    "timeout_seconds": timeout_seconds,
                },
            )
        )


def test_llm_success_records_start_and_end_events() -> None:
    """A successful LLM node should emit start and end diagnostics."""

    client = FakeLLMClient(
        [
            LLMResponse(
                content='{"command": "analyze", "intent": "direct_analysis"}',
                model="fake-model",
                metadata={"provider": "fake"},
            )
        ]
    )
    state = AgentState(session_id="session-1", job_id="job-1", user_message="Analyze data")

    route(state, strategy="llm", llm_client=client)

    llm_events = _llm_events(state)
    assert [event.event_type for event in llm_events] == [
        EventType.LLM_START,
        EventType.LLM_END,
    ]
    assert llm_events[0].payload["node_name"] == "route"
    assert llm_events[0].payload["prompt_name"] == "router"
    assert set(llm_events[0].payload["input_keys"]) == {
        "current_command",
        "current_intent",
        "agent_context_summary",
        "is_followup_correction",
        "last_user_question",
        "task",
        "user_message",
    }
    assert llm_events[1].payload["provider"] == "fake"
    assert llm_events[1].payload["model"] == "fake-model"
    assert _events_do_not_contain(llm_events, "messages")
    assert _events_do_not_contain(llm_events, "content")
    assert _events_do_not_contain(llm_events, "system_prompt")


def test_invalid_json_records_json_invalid_and_fallback() -> None:
    """Invalid LLM JSON should be visible and still fall back to rule insight."""

    state = _insight_state()

    generate_insight(state, strategy="llm", llm_client=FakeLLMClient(["not-json"]))

    llm_events = _llm_events(state)
    assert [event.event_type for event in llm_events] == [
        EventType.LLM_START,
        EventType.LLM_END,
        EventType.LLM_JSON_INVALID,
        EventType.LLM_FALLBACK,
    ]
    json_invalid = _event_of_type(state, EventType.LLM_JSON_INVALID)
    fallback = _event_of_type(state, EventType.LLM_FALLBACK)
    assert json_invalid.payload["error_code"] == "json_invalid"
    assert json_invalid.payload["metadata"]["content_length"] == len("not-json")
    assert fallback.payload["node_name"] == "generate_insight"
    assert fallback.payload["fallback_reason"] == "LLM output did not contain a JSON object."
    assert fallback.payload["switched_to_rule_strategy"] is True
    assert state.insights[0].title == "\u89c4\u5219\u5206\u6790\u6d1e\u5bdf"
    assert _events_do_not_contain(llm_events, "not-json")


def test_llm_error_records_error_and_fallback() -> None:
    """Provider errors should be recorded before deterministic fallback runs."""

    state = _insight_state()

    generate_insight(state, strategy="llm", llm_client=FakeLLMClient())

    llm_events = _llm_events(state)
    assert [event.event_type for event in llm_events] == [
        EventType.LLM_START,
        EventType.LLM_ERROR,
        EventType.LLM_FALLBACK,
    ]
    error = _event_of_type(state, EventType.LLM_ERROR)
    fallback = _event_of_type(state, EventType.LLM_FALLBACK)
    assert error.payload["error_code"] == "fake_response_exhausted"
    assert fallback.payload["error_code"] == "fake_response_exhausted"
    assert fallback.payload["switched_to_rule_strategy"] is True
    assert state.insights[0].summary == "\u6c47\u603b\u7ed3\u679c\u4e3a 310.0\u3002"


def test_llm_diagnostics_do_not_leak_api_key() -> None:
    """LLM events should redact credential-shaped text from errors and metadata."""

    state = _insight_state()

    generate_insight(state, strategy="llm", llm_client=SecretFailingLLMClient())

    serialized_events = json.dumps(
        [event.model_dump(mode="json") for event in _llm_events(state)],
        sort_keys=True,
    )
    assert "fake-secret" not in serialized_events
    assert "<redacted>" in serialized_events
    assert state.insights[0].title == "\u89c4\u5219\u5206\u6790\u6d1e\u5bdf"


def test_job_runner_event_store_exposes_llm_events(sqlite_data_source) -> None:
    """Job runner should copy LLM AgentState events into its event store."""

    client = FakeLLMClient(
        [
            LLMResponse(
                content=(
                    '{"title": "LLM 收入洞察", "summary": "收入汇总为 310。", '
                    '"evidence": ["total_revenue=310"], "confidence": 0.8}'
                ),
                model="fake-model",
                metadata={"provider": "fake"},
            )
        ]
    )
    runner = InMemoryJobRunner(
        data_source=sqlite_data_source,
        llm_client=client,
        node_strategies={"generate_insight": "llm"},
    )
    state = build_initial_state(
        session_id="session-1",
        user_message="What is total revenue?",
        command=AgentCommand.ANALYZE,
    )

    job = runner.submit(state)

    assert job.status is JobStatus.COMPLETED
    assert job.intent is AgentIntent.DIRECT_ANALYSIS
    assert job.final_state is not None
    assert job.final_state.insights[0].title == "LLM 收入洞察"
    event_types = [event.event_type for event in runner.list_events(job.job_id)]
    assert EventType.LLM_START in event_types
    assert EventType.LLM_END in event_types


def _insight_state() -> AgentState:
    """Create the minimal state required by generate_insight."""

    return AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="What is total revenue?",
        question_interpretation=QuestionInterpretation(
            question="What is total revenue?",
            kind=DirectQuestionKind.SUMMARY,
            table_name="orders",
            metric_field="orders.revenue",
        ),
        sql_result=QueryResult(
            sql="SELECT SUM(revenue) AS total_revenue FROM orders",
            columns=[QueryColumn(name="total_revenue", data_type="real")],
            rows=[{"total_revenue": 310.0}],
            row_count=1,
        ),
    )


def _llm_events(state: AgentState) -> list:
    """Return only LLM observability events from state."""

    return [event for event in state.events if event.event_type.value.startswith("llm_")]


def _event_of_type(state: AgentState, event_type: EventType):
    """Return the first LLM event of a specific type."""

    return next(event for event in _llm_events(state) if event.event_type is event_type)


def _events_do_not_contain(events: list, needle: str) -> bool:
    """Return whether serialized event payloads exclude a sensitive substring."""

    serialized_events = json.dumps(
        [event.model_dump(mode="json") for event in events],
        sort_keys=True,
    )
    return needle not in serialized_events

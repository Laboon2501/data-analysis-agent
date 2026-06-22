"""Tests for chart artifact generation node behavior."""

import json

from nodes.chart_nodes import decide_chart, generate_chart_artifact
from persistence import InMemoryArtifactStore
from schemas import AgentState, DirectQuestionKind, EventType
from schemas.direct_analysis import QuestionInterpretation
from schemas.query_result import QueryColumn, QueryResult


def test_generate_chart_artifact_updates_chart_spec_and_event() -> None:
    """The chart node should save an artifact and emit only a chart_ref event."""

    artifact_store = InMemoryArtifactStore()
    state = _state_with_query_result()
    decide_chart(state)

    generate_chart_artifact(state, artifact_store=artifact_store)

    assert state.chart_spec is not None
    assert state.chart_spec.artifact_ref is not None
    record = artifact_store.get_artifact(state.chart_spec.artifact_ref)
    assert record is not None
    assert record.metadata["chart_type"] == "line"
    chart_events = [event for event in state.events if event.event_type is EventType.CHART_REF]
    assert len(chart_events) == 1
    payload = chart_events[0].payload
    assert payload["artifact_ref"] == state.chart_spec.artifact_ref
    assert payload["artifact_id"] == state.chart_spec.artifact_ref.rsplit(":", maxsplit=1)[-1]
    assert payload["mime_type"] == record.metadata["mime_type"]
    serialized_payload = json.dumps(payload, sort_keys=True)
    assert "chart_artifact" not in serialized_payload
    assert "2026-01" not in serialized_payload
    assert "chart_html" not in serialized_payload


def test_generate_chart_artifact_skips_when_chart_is_unavailable() -> None:
    """Missing chart specs or query results should leave state unchanged."""

    state = AgentState(session_id="session-1", job_id="job-1", user_message="empty")

    generate_chart_artifact(state, artifact_store=InMemoryArtifactStore())

    assert state.chart_spec is None
    assert state.events == []


def _state_with_query_result() -> AgentState:
    """Build state that can pass through decide_chart."""

    return AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="Show monthly revenue trend",
        question_interpretation=QuestionInterpretation(
            question="Show monthly revenue trend",
            kind=DirectQuestionKind.TIME_TREND,
            table_name="orders",
            metric_field="orders.revenue",
            time_field="orders.month",
        ),
        sql_result=QueryResult(
            sql="SELECT month, SUM(revenue) AS total_revenue FROM orders GROUP BY month",
            columns=[
                QueryColumn(name="month", data_type="text"),
                QueryColumn(name="total_revenue", data_type="real"),
            ],
            rows=[
                {"month": "2026-01", "total_revenue": 100.0},
                {"month": "2026-02", "total_revenue": 210.0},
            ],
            row_count=2,
        ),
    )

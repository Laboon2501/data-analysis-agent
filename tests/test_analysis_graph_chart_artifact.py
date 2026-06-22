"""End-to-end tests for chart artifact generation in the analysis graph."""

import json

from graphs.analysis_graph import build_analysis_graph
from persistence import InMemoryArtifactStore, InMemoryCacheStore
from schemas import AgentState, ChartType, EventType


def test_analysis_graph_generates_chart_artifact(sqlite_data_source) -> None:
    """Direct analysis should save a chart artifact and package its reference."""

    artifact_store = InMemoryArtifactStore()
    graph = build_analysis_graph(
        data_source=sqlite_data_source,
        cache_store=InMemoryCacheStore(),
        artifact_store=artifact_store,
    )

    state = AgentState.model_validate(
        graph.invoke(
            AgentState(
                session_id="session-1",
                job_id="job-1",
                user_message="Show monthly revenue trend",
                datasource_id=sqlite_data_source.datasource_id,
            )
        )
    )

    assert state.chart_spec is not None
    assert state.chart_spec.chart_type is ChartType.LINE
    assert state.chart_spec.artifact_ref is not None
    artifact_record = artifact_store.get_artifact(state.chart_spec.artifact_ref)
    assert artifact_record is not None
    assert artifact_record.metadata["artifact_kind"] == "chart"
    assert artifact_record.content["chart"]["chart_id"] == state.chart_spec.chart_id
    assert state.analysis_package is not None
    assert state.analysis_package.chart_spec == state.chart_spec
    assert state.chart_spec.artifact_ref in state.analysis_package.artifact_refs


def test_analysis_graph_chart_ref_event_excludes_artifact_body(sqlite_data_source) -> None:
    """chart_ref events should carry metadata only, not JSON chart content."""

    graph = build_analysis_graph(
        data_source=sqlite_data_source,
        cache_store=InMemoryCacheStore(),
        artifact_store=InMemoryArtifactStore(),
    )

    state = AgentState.model_validate(
        graph.invoke(
            AgentState(
                session_id="session-1",
                job_id="job-1",
                user_message="What is total revenue?",
                datasource_id=sqlite_data_source.datasource_id,
            )
        )
    )

    chart_events = [event for event in state.events if event.event_type is EventType.CHART_REF]

    assert len(chart_events) == 1
    payload = chart_events[0].payload
    assert payload["artifact_ref"] == state.chart_spec.artifact_ref
    assert payload["metadata"]["chart_type"] == "table"
    serialized_payload = json.dumps(payload, sort_keys=True)
    assert "chart_artifact" not in serialized_payload
    assert '"rows"' not in serialized_payload
    assert "310.0" not in serialized_payload
    assert "chart_html" not in serialized_payload

"""Rule-based chart decision nodes."""

from __future__ import annotations

from persistence.interfaces import ArtifactStore
from schemas.agent_state import AgentState
from schemas.chart import ChartSpec, ChartType
from schemas.direct_analysis import DirectQuestionKind
from schemas.event import AgentEvent, EventType
from schemas.query_result import QueryResult
from tools.chart_tools import chart_artifact_metadata, chart_ref_payload, generate_chart


def decide_chart(state: AgentState) -> AgentState:
    """Select a chart specification without rendering chart artifacts."""

    if state.question_interpretation is None:
        raise ValueError("QuestionInterpretation is required before chart decision.")
    if state.sql_result is None or (
        state.result_check is not None and not state.result_check.is_valid
    ):
        state.chart_spec = ChartSpec(
            chart_type=ChartType.NONE,
            title="No chart available",
            rationale="SQL result is missing or invalid.",
        )
        return state

    interpretation = state.question_interpretation
    if interpretation.kind is DirectQuestionKind.TIME_TREND:
        chart_type = ChartType.LINE
        x = _column_name(interpretation.time_field)
        y = _measure_column_name(state.sql_result)
    elif interpretation.kind is DirectQuestionKind.TOP_N:
        chart_type = ChartType.BAR
        x = _column_name(interpretation.dimension_field)
        y = _measure_column_name(state.sql_result)
    else:
        chart_type = ChartType.TABLE
        x = None
        y = _measure_column_name(state.sql_result)

    state.chart_spec = ChartSpec(
        chart_type=chart_type,
        title=f"{interpretation.kind.value.replace('_', ' ').title()} Analysis",
        x=x,
        y=y,
        rationale="Rule-based chart selection; no chart artifact generated.",
    )
    return state


def generate_chart_artifact(
    state: AgentState,
    *,
    artifact_store: ArtifactStore,
) -> AgentState:
    """Persist a chart artifact reference without putting rendered content in state."""

    if state.chart_spec is None or state.sql_result is None:
        return state

    metadata = chart_artifact_metadata(state.chart_spec, state.sql_result)
    artifact_ref = generate_chart(
        state.chart_spec,
        state.sql_result,
        artifact_store=artifact_store,
    )
    if artifact_ref is None:
        return state

    state.chart_spec = state.chart_spec.model_copy(update={"artifact_ref": artifact_ref})
    state.events.append(
        AgentEvent(
            event_type=EventType.CHART_REF,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name="generate_chart_artifact",
            message="Chart artifact generated.",
            payload=chart_ref_payload(artifact_ref, metadata),
        )
    )
    return state


def _column_name(field: str | None) -> str | None:
    """Return a column name from a table-qualified field."""

    if field is None:
        return None
    return field.split(".", maxsplit=1)[-1]


def _measure_column_name(query_result: QueryResult) -> str | None:
    """Return the aggregate column name selected by SQL drafting."""

    for column in query_result.columns:
        if column.name.startswith("total_"):
            return column.name
    return query_result.columns[-1].name if query_result.columns else None

"""Final packaging nodes for direct analysis."""

from __future__ import annotations

from schemas.agent_state import AgentState
from schemas.analysis_package import AnalysisPackage
from schemas.event import AgentEvent, EventType


def build_analysis_package(state: AgentState) -> AgentState:
    """Assemble the direct analysis package from structured state."""

    state.analysis_package = AnalysisPackage(
        question=state.user_message,
        analysis_plan=state.analysis_plan,
        sql_result=state.sql_result,
        chart_spec=state.chart_spec,
        insights=state.insights,
        artifact_refs=_artifact_refs_from_state(state),
    )
    return state


def final_response(state: AgentState) -> AgentState:
    """Create a concise final response string and completion events."""

    if state.analysis_package is None:
        raise ValueError("AnalysisPackage is required before final response.")
    insight_summary = state.insights[0].summary if state.insights else "分析已完成。"
    state.last_user_question = state.user_message
    state.last_question_interpretation = state.question_interpretation
    state.last_analysis_plan = state.analysis_plan
    state.last_sql_draft = state.sql_draft
    state.last_sql_result_summary = _query_result_summary(state)
    state.last_chart_spec = state.chart_spec
    state.final_response_text = insight_summary
    state.events.append(
        AgentEvent(
            event_type=EventType.TEXT_DELTA,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name="final_response",
            message=insight_summary,
        )
    )
    state.events.append(
        AgentEvent(
            event_type=EventType.DONE,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name="final_response",
            message="明确问题分析已完成。",
        )
    )
    return state


def _artifact_refs_from_state(state: AgentState) -> list[str]:
    """Collect generated artifact references for the final package."""

    refs: list[str] = []
    if state.chart_spec is not None and state.chart_spec.artifact_ref is not None:
        refs.append(state.chart_spec.artifact_ref)
    return refs


def _query_result_summary(state: AgentState) -> dict[str, int | str | None] | None:
    """Keep only small SQL result metadata for later follow-up correction."""

    if state.sql_result is None:
        return None
    return {
        "row_count": state.sql_result.row_count,
        "column_count": len(state.sql_result.columns),
        "first_column": state.sql_result.columns[0].name if state.sql_result.columns else None,
    }

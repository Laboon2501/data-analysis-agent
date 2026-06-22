"""Tests for the explicit workflow state and schema contracts."""

from schemas import (
    AgentState,
    DatabaseProfile,
    EventType,
    FieldProfile,
    ProfileStatus,
    ReportFormat,
    ReportOutline,
    SimilarCase,
    TableProfile,
)
from schemas.analysis_plan import AnalysisMode, AnalysisPlan, AnalysisStep
from schemas.chart import ChartSpec, ChartType
from schemas.event import AgentEvent
from schemas.human import HumanRequest, HumanRequestType


def test_agent_state_contains_required_workflow_fields() -> None:
    """AgentState must expose every core field required by AGENTS.md."""

    expected_fields = {
        "session_id",
        "job_id",
        "user_message",
        "command",
        "intent",
        "router_decision",
        "datasource_id",
        "database_profile",
        "profile_status",
        "similar_cases",
        "business_rules",
        "question_interpretation",
        "analysis_plan",
        "exploration_plan",
        "sql_draft",
        "sql_validation",
        "sql_result",
        "result_check",
        "chart_spec",
        "insights",
        "exploration_findings",
        "exploration_summary",
        "analysis_package",
        "report_outline",
        "report_result",
        "human_request",
        "needs_human",
        "final_response_text",
        "retry_count_by_node",
        "error_count",
        "errors",
        "events",
    }

    assert expected_fields.issubset(AgentState.model_fields)


def test_agent_state_has_safe_defaults() -> None:
    """A new state should start empty and explicit, without hidden chat context."""

    state = AgentState(session_id="session-1", job_id="job-1", user_message="sales by month")

    assert state.profile_status is ProfileStatus.MISSING
    assert state.database_profile is None
    assert state.question_interpretation is None
    assert state.analysis_plan is None
    assert state.exploration_plan is None
    assert state.result_check is None
    assert state.exploration_findings == []
    assert state.exploration_summary is None
    assert state.report_outline is None
    assert state.needs_human is False
    assert state.final_response_text is None
    assert state.retry_count_by_node == {}
    assert state.events == []


def test_agent_state_accepts_structured_similar_cases() -> None:
    """Similar cases should be typed schema objects instead of loose dict state."""

    similar_case = SimilarCase(
        user_question="What was revenue by month?",
        sql="SELECT month, revenue FROM monthly_revenue",
        chart_type="bar",
        insight_summary="Revenue increased across the period.",
        user_correction="Use net revenue instead of gross revenue.",
        score=0.92,
        metadata={"datasource_id": "warehouse"},
    )
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="sales by month",
        similar_cases=[similar_case],
    )

    assert state.similar_cases == [similar_case]
    assert state.similar_cases[0].metadata["datasource_id"] == "warehouse"


def test_agent_state_can_store_report_outline_for_export_fast_path() -> None:
    """Report outline should stay in state so confirmed exports can skip replanning."""

    outline = ReportOutline(
        report_format=ReportFormat.REPORT,
        title="Sales performance report",
        source_package_id="package-1",
    )
    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="export report",
        report_outline=outline,
    )

    assert state.report_outline == outline
    assert state.report_outline.requires_confirmation is True


def test_database_profile_captures_clean_confirmable_metadata() -> None:
    """DatabaseProfile should store table metadata without profiling scratch context."""

    profile = DatabaseProfile(
        datasource_id="warehouse",
        schema_hash="hash-1",
        status=ProfileStatus.CONFIRMED,
        tables=[
            TableProfile(
                name="orders",
                row_count=10,
                columns=[
                    FieldProfile(
                        name="order_id",
                        data_type="integer",
                        sample_values=[1, 2],
                    )
                ],
                primary_key=["order_id"],
            )
        ],
        metric_fields=["orders.revenue"],
        dimension_fields=["orders.region"],
    )

    assert profile.datasource_id == "warehouse"
    assert profile.tables[0].columns[0].name == "order_id"
    assert profile.metric_fields == ["orders.revenue"]


def test_analysis_plan_human_request_chart_and_event_schemas() -> None:
    """Core adjacent schemas should be instantiable without business execution."""

    plan = AnalysisPlan(
        mode=AnalysisMode.DIRECT,
        question="sales by month",
        steps=[
            AnalysisStep(
                name="draft_sql",
                objective="Prepare candidate SQL after validation planning.",
                tool_categories=["sql"],
            )
        ],
    )
    human_request = HumanRequest(
        request_type=HumanRequestType.SQL_RISK_CONFIRMATION,
        prompt="Confirm before running a high-risk query.",
    )
    chart_spec = ChartSpec(chart_type=ChartType.BAR, title="Sales by month")
    event = AgentEvent(event_type=EventType.HUMAN_REQUEST, payload={"id": human_request.request_id})

    assert plan.steps[0].tool_categories == ["sql"]
    assert human_request.required is True
    assert chart_spec.artifact_ref is None
    assert event.event_type is EventType.HUMAN_REQUEST


def test_event_type_contract_matches_required_stream_events() -> None:
    """EventType must cover the structured stream events listed in AGENTS.md."""

    expected_events = {
        "node_start",
        "node_end",
        "tool_start",
        "tool_end",
        "text_delta",
        "chart_ref",
        "artifact_ref",
        "human_request",
        "usage",
        "llm_start",
        "llm_end",
        "llm_error",
        "llm_fallback",
        "llm_json_invalid",
        "done",
        "error",
        "stopped",
    }

    assert expected_events == {event_type.value for event_type in EventType}

"""Tests for the synchronous in-memory job runner."""

from app.harness import build_initial_state
from app.workers import InMemoryJobRunner, JobStatus
from schemas import (
    AgentCommand,
    AgentIntent,
    ChartSpec,
    ChartType,
    Insight,
    ReportFormat,
)
from schemas.analysis_package import AnalysisPackage
from schemas.event import EventType
from schemas.query_result import QueryColumn, QueryResult


def _analysis_package() -> AnalysisPackage:
    """Create a structured package that can feed report outline generation."""

    return AnalysisPackage(
        question="What is total revenue?",
        sql_result=QueryResult(
            sql="SELECT SUM(revenue) AS total_revenue FROM orders",
            columns=[QueryColumn(name="total_revenue", data_type="real")],
            rows=[{"total_revenue": 310.0}],
            row_count=1,
        ),
        chart_spec=ChartSpec(chart_type=ChartType.TABLE, title="Total revenue"),
        insights=[
            Insight(
                title="Revenue summary",
                summary="\u6c47\u603b\u7ed3\u679c\u4e3a 310.0\u3002",
            )
        ],
    )


def test_job_runner_completes_direct_analysis_job(sqlite_data_source) -> None:
    """A direct analysis state should run through the existing analysis graph."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    state = build_initial_state(
        session_id="session-1",
        user_message="What is total revenue?",
    )

    job = runner.submit(state)

    assert job.status is JobStatus.COMPLETED
    assert job.intent is AgentIntent.DIRECT_ANALYSIS
    assert job.final_state is not None
    assert job.final_state.analysis_package is not None
    assert job.final_state.final_response_text == "\u6c47\u603b\u7ed3\u679c\u4e3a 310.0\u3002"
    assert runner.get_job(job.job_id).status is JobStatus.COMPLETED
    assert runner.list_events(job.job_id)
    assert _event_count(runner.list_events(job.job_id), EventType.DONE) == 1


def test_job_runner_answers_chat_without_sql_or_datasource() -> None:
    """Chat/help requests should complete without building an analysis graph."""

    runner = InMemoryJobRunner()
    state = build_initial_state(
        session_id="session-1",
        user_message="hi",
    )

    job = runner.submit(state)

    assert job.status is JobStatus.COMPLETED
    assert job.intent is AgentIntent.CLARIFICATION
    assert job.final_state is not None
    assert job.final_state.sql_draft is None
    assert job.final_state.sql_result is None
    assert job.final_state.analysis_package is None
    assert "数据分析 Agent" in job.final_state.final_response_text
    event_types = [event.event_type for event in runner.list_events(job.job_id)]
    assert EventType.TEXT_DELTA in event_types
    assert event_types.count(EventType.DONE) == 1


def test_job_runner_can_call_context_manager_graph(sqlite_data_source) -> None:
    """Profile requests should execute the Context Manager graph."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    state = build_initial_state(
        session_id="session-1",
        user_message="Profile the database schema",
    )

    job = runner.submit(state)

    assert job.status is JobStatus.COMPLETED
    assert job.intent is AgentIntent.CONTEXT_MANAGER
    assert job.final_state is not None
    assert job.final_state.database_profile is not None
    assert job.final_state.database_profile.datasource_id == sqlite_data_source.datasource_id


def test_job_runner_stops_report_job_for_human_confirmation(sqlite_data_source) -> None:
    """Report outline generation should finish in waiting_for_human state."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    state = build_initial_state(
        session_id="session-1",
        user_message="export report",
        command=AgentCommand.REPORT,
        analysis_package=_analysis_package(),
    )

    job = runner.submit(state)

    assert job.status is JobStatus.WAITING_FOR_HUMAN
    assert job.final_state is not None
    assert job.final_state.report_outline is not None
    assert job.final_state.needs_human is True
    assert job.final_state.report_result is None
    assert _event_count(runner.list_events(job.job_id), EventType.HUMAN_REQUEST) == 1


def test_job_runner_approve_resumes_report_fast_path(sqlite_data_source) -> None:
    """Approving a report outline should reuse it and create an artifact reference."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    waiting_job = runner.submit(
        build_initial_state(
            session_id="session-1",
            user_message="export report",
            command=AgentCommand.REPORT,
            analysis_package=_analysis_package(),
        )
    )
    outline_id = waiting_job.final_state.report_outline.outline_id

    completed_job = runner.approve_job(waiting_job.job_id, AgentCommand.REPORT_CONFIRM)

    assert completed_job.status is JobStatus.COMPLETED
    assert completed_job.command is AgentCommand.REPORT_CONFIRM
    assert completed_job.final_state is not None
    assert completed_job.final_state.report_outline.outline_id == outline_id
    assert completed_job.final_state.report_result is not None
    assert completed_job.final_state.report_result.report_format is ReportFormat.REPORT
    assert completed_job.final_state.report_result.artifact_ref.startswith("artifact:")


def test_job_runner_cancel_sets_flag_and_stopped_event(sqlite_data_source) -> None:
    """Cancel should set the cancel flag and append a stopped event."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    waiting_job = runner.submit(
        build_initial_state(
            session_id="session-1",
            user_message="export report",
            command=AgentCommand.REPORT,
            analysis_package=_analysis_package(),
        )
    )

    cancelled_job = runner.cancel_job(waiting_job.job_id)

    assert cancelled_job.status is JobStatus.CANCELLED
    assert runner.cancel_policy.is_cancelled(waiting_job.job_id) is True
    assert any(
        event.event_type is EventType.STOPPED for event in runner.list_events(waiting_job.job_id)
    )


def _event_count(events, event_type: EventType) -> int:
    """Count events of one type in a job event list."""

    return sum(1 for event in events if event.event_type is event_type)

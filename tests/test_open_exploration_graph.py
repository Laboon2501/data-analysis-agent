"""Tests for the rule-based open exploration graph."""

from datasource import SQLAlchemyDataSource
from graphs.open_exploration_graph import build_open_exploration_graph
from persistence import InMemoryCacheStore
from schemas import (
    AgentCommand,
    AgentIntent,
    AgentState,
    DirectQuestionKind,
    HumanRequestType,
)


def _run_open_exploration(
    sqlite_data_source: SQLAlchemyDataSource,
    *,
    top_n: int = 3,
    require_human_confirmation: bool = False,
) -> AgentState:
    """Run the open exploration graph and validate the returned state."""

    graph = build_open_exploration_graph(
        data_source=sqlite_data_source,
        cache_store=InMemoryCacheStore(),
        top_n=top_n,
        require_human_confirmation=require_human_confirmation,
    )
    result = graph.invoke(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="Explore this datasource",
            datasource_id=sqlite_data_source.datasource_id,
        )
    )
    return AgentState.model_validate(result)


def test_open_exploration_generates_candidate_topics(sqlite_data_source) -> None:
    """generate_analysis_map should create profile-backed candidate topics."""

    state = _run_open_exploration(sqlite_data_source, top_n=3)
    assert state.command is AgentCommand.EXPLORE
    assert state.intent is AgentIntent.OPEN_EXPLORATION
    assert state.exploration_plan is not None

    topics = state.exploration_plan.topics
    assert {topic.kind for topic in topics} == {
        DirectQuestionKind.SUMMARY,
        DirectQuestionKind.TIME_TREND,
        DirectQuestionKind.TOP_N,
    }
    assert {topic.metric_field for topic in topics} == {"orders.revenue"}


def test_open_exploration_ranks_topics_by_rule_priority(sqlite_data_source) -> None:
    """rank_topics should prefer time trend, then actionable TopN before summary."""

    state = _run_open_exploration(sqlite_data_source, top_n=3)
    assert state.exploration_plan is not None

    ranked_topics = state.exploration_plan.topics
    assert [topic.kind for topic in ranked_topics[:3]] == [
        DirectQuestionKind.TIME_TREND,
        DirectQuestionKind.TOP_N,
        DirectQuestionKind.SUMMARY,
    ]
    assert ranked_topics[0].priority_score > ranked_topics[1].priority_score
    assert len(state.exploration_plan.selected_topic_ids) == 3


def test_open_exploration_runs_top_n_rule_based_analyses(sqlite_data_source) -> None:
    """run_top_n_analyses should execute selected topics through direct nodes."""

    state = _run_open_exploration(sqlite_data_source, top_n=3)

    assert len(state.exploration_findings) == 3
    assert all(finding.status == "completed" for finding in state.exploration_findings)
    assert any("GROUP BY month" in (finding.sql or "") for finding in state.exploration_findings)
    assert any(
        "GROUP BY customer_id" in (finding.sql or "") for finding in state.exploration_findings
    )
    assert all(finding.insights for finding in state.exploration_findings)


def test_open_exploration_writes_human_request_placeholder(sqlite_data_source) -> None:
    """optional_human_confirm should write a placeholder while allowing tests to skip."""

    state = _run_open_exploration(
        sqlite_data_source,
        top_n=2,
        require_human_confirmation=False,
    )

    assert state.human_request is not None
    assert state.human_request.request_type is HumanRequestType.EXPLORATION_PLAN_CONFIRMATION
    assert state.needs_human is False
    assert state.exploration_plan is not None
    assert state.exploration_plan.requires_human_confirmation is False


def test_open_exploration_generates_analysis_package(sqlite_data_source) -> None:
    """Open exploration should summarize findings into an AnalysisPackage."""

    state = _run_open_exploration(sqlite_data_source, top_n=2)

    assert state.exploration_summary is not None
    assert "已完成开放探索，自动分析了 2 个方向" in state.exploration_summary.summary
    assert "可继续追问" in state.exploration_summary.summary
    assert "可导出" in state.exploration_summary.summary
    assert len(state.exploration_summary.key_points) == 2
    assert state.analysis_package is not None
    assert state.analysis_package.question == "Explore this datasource"
    assert len(state.analysis_package.insights) == 2
    assert state.final_response_text == state.exploration_summary.summary

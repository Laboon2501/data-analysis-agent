"""Tests for app-level state construction and deterministic routing."""

from app.harness import build_initial_state, infer_command_and_intent
from schemas import AgentCommand, AgentIntent


def test_build_initial_state_defaults_to_direct_analysis() -> None:
    """Plain analytical questions should route to direct analysis."""

    state = build_initial_state(
        session_id="session-1",
        user_message="What is total revenue?",
        datasource_id="warehouse",
    )

    assert state.job_id
    assert state.datasource_id == "warehouse"
    assert state.command is AgentCommand.ANALYZE
    assert state.intent is AgentIntent.DIRECT_ANALYSIS


def test_build_initial_state_routes_chat_help_to_clarification() -> None:
    """Greetings and help requests should not trigger SQL analysis."""

    for message in ("hi", "hello", "你好", "在吗", "help", "你能做什么"):
        state = build_initial_state(
            session_id="session-1",
            user_message=message,
        )

        assert state.command is AgentCommand.NONE
        assert state.intent is AgentIntent.CLARIFICATION


def test_build_initial_state_routes_meaningless_input_to_clarification() -> None:
    """Unclear text should ask for a valid analysis question instead of querying data."""

    state = build_initial_state(
        session_id="session-1",
        user_message="asdf qwer",
    )

    assert state.command is AgentCommand.NONE
    assert state.intent is AgentIntent.CLARIFICATION


def test_explicit_analyze_command_does_not_force_chat_into_sql() -> None:
    """An explicit analyze command should still require a clear analysis request."""

    state = build_initial_state(
        session_id="session-1",
        user_message="hi",
        command=AgentCommand.ANALYZE,
    )

    assert state.command is AgentCommand.NONE
    assert state.intent is AgentIntent.CLARIFICATION


def test_build_initial_state_routes_open_exploration() -> None:
    """Exploration keywords should route to the open exploration graph."""

    state = build_initial_state(
        session_id="session-1",
        user_message="Explore this datasource",
    )

    assert state.command is AgentCommand.EXPLORE
    assert state.intent is AgentIntent.OPEN_EXPLORATION


def test_build_initial_state_routes_chinese_exploration_request() -> None:
    """Chinese broad datasource exploration should route to open exploration."""

    state = build_initial_state(
        session_id="session-1",
        user_message="帮我看看这个数据库有什么可以分析的",
    )

    assert state.command is AgentCommand.EXPLORE
    assert state.intent is AgentIntent.OPEN_EXPLORATION


def test_build_initial_state_routes_report_and_confirm_commands() -> None:
    """Report requests and confirm commands should route to report export."""

    report_state = build_initial_state(
        session_id="session-1",
        user_message="Please export a report",
    )
    confirm_state = build_initial_state(
        session_id="session-1",
        user_message="confirmed ppt",
        command=AgentCommand.PPT_CONFIRM,
    )

    assert report_state.command is AgentCommand.REPORT
    assert report_state.intent is AgentIntent.REPORT_EXPORT
    assert confirm_state.command is AgentCommand.PPT_CONFIRM
    assert confirm_state.intent is AgentIntent.REPORT_EXPORT


def test_build_initial_state_routes_context_manager_profile_requests() -> None:
    """Schema/profile requests should route to the Context Manager graph."""

    state = build_initial_state(
        session_id="session-1",
        user_message="Profile the database schema",
    )

    assert state.command is AgentCommand.PROFILE
    assert state.intent is AgentIntent.CONTEXT_MANAGER


def test_infer_command_and_intent_maps_confirm_keywords_exactly() -> None:
    """Confirm keyword routing should preserve the requested export target."""

    assert infer_command_and_intent("ppt_confirm") == (
        AgentCommand.PPT_CONFIRM,
        AgentIntent.REPORT_EXPORT,
    )
    assert infer_command_and_intent("excel_confirm") == (
        AgentCommand.EXCEL_CONFIRM,
        AgentIntent.REPORT_EXPORT,
    )

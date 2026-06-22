"""Routing tests for schema QA / data inspection intent."""

from app.harness import build_initial_state, infer_command_and_intent
from schemas import AgentCommand, AgentIntent


def test_schema_field_questions_route_to_schema_qa() -> None:
    """字段/列说明问题不应进入 direct analysis 或 context profile fast-path。"""

    for message in (
        "有哪些字段",
        "把字段告诉我",
        "这个表有哪些列",
        "每个字段是什么意思",
        "哪些字段可以分析",
        "哪些是指标字段",
        "哪些是维度字段",
        "上传的文件有什么字段",
        "这个数据文件能分析什么",
    ):
        command, intent = infer_command_and_intent(message)
        state = build_initial_state(session_id="schema-route", user_message=message)

        assert command is AgentCommand.SCHEMA_QA
        assert intent is AgentIntent.SCHEMA_QA
        assert state.command is AgentCommand.SCHEMA_QA
        assert state.intent is AgentIntent.SCHEMA_QA


def test_schema_qa_followup_overrides_direct_analysis_correction() -> None:
    """纠正句如果明确问字段，应进入 schema QA，而不是沿用上一轮分析。"""

    state = build_initial_state(
        session_id="schema-route",
        user_message="不是，我是问字段，把字段告诉我",
    )

    assert state.command is AgentCommand.SCHEMA_QA
    assert state.intent is AgentIntent.SCHEMA_QA


def test_open_exploration_request_still_routes_to_exploration() -> None:
    """明确让系统自动探索时仍走 open exploration。"""

    state = build_initial_state(
        session_id="schema-route",
        user_message="帮我看看这个数据库有什么可以分析的",
    )

    assert state.command is AgentCommand.EXPLORE
    assert state.intent is AgentIntent.OPEN_EXPLORATION

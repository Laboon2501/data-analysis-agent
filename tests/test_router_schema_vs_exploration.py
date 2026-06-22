"""Rule router boundary tests for schema QA and open exploration."""

from app.harness import build_initial_state
from schemas import AgentCommand, AgentIntent


def test_explicit_field_questions_route_to_schema_qa() -> None:
    """明确询问字段/列时才进入 schema QA。"""

    for message in ("把字段告诉我", "这个文件有哪些字段？", "这个表有哪些列？"):
        state = build_initial_state(session_id="router-boundary", user_message=message)

        assert state.command is AgentCommand.SCHEMA_QA
        assert state.intent is AgentIntent.SCHEMA_QA


def test_exploratory_analysis_requests_route_to_open_exploration() -> None:
    """自动探索、看看发现、有什么可以分析应进入 open exploration。"""

    for message in (
        "帮我探索性地分析一下这张表的数据",
        "这张表有什么可以分析的吗",
        "帮我看看这个数据有什么问题和亮点",
    ):
        state = build_initial_state(session_id="router-boundary", user_message=message)

        assert state.command is AgentCommand.EXPLORE
        assert state.intent is AgentIntent.OPEN_EXPLORATION

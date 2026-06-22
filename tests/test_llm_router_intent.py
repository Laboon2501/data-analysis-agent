"""LLM-first router intent tests."""

from app.harness import LLMNodeStrategyConfig, build_initial_state
from llm.fake import FakeLLMClient
from schemas import AgentCommand, AgentIntent, EventType


def test_llm_router_can_select_open_exploration() -> None:
    """启用 router 节点时，LLM intent 应优先决定开放探索入口。"""

    client = FakeLLMClient(
        [
            (
                '{"intent":"open_exploration","confidence":0.93,'
                '"reason":"用户要求探索性分析。","needs_datasource":true,'
                '"is_followup":false,"referenced_previous_context":false}'
            )
        ]
    )

    state = build_initial_state(
        session_id="router-session",
        user_message="帮我探索性地分析一下这张表的数据",
        llm_client=client,
        llm_strategy_config=LLMNodeStrategyConfig(enabled_nodes=["router"]),
    )

    assert state.command is AgentCommand.EXPLORE
    assert state.intent is AgentIntent.OPEN_EXPLORATION
    assert state.router_decision is not None
    assert state.router_decision.source == "llm"
    assert state.router_decision.intent == AgentIntent.OPEN_EXPLORATION.value
    assert len(client.calls) == 1
    assert "SELECT" not in client.calls[0][1].content.upper()


def test_llm_router_invalid_json_falls_back_to_rule_router() -> None:
    """LLM router JSON 异常时，应回退到规则路由而不是默认 direct analysis。"""

    client = FakeLLMClient(["not-json"])

    state = build_initial_state(
        session_id="router-session",
        user_message="帮我探索性地分析一下这张表的数据",
        llm_client=client,
        llm_strategy_config=LLMNodeStrategyConfig(enabled_nodes=["router"]),
    )

    assert state.command is AgentCommand.EXPLORE
    assert state.intent is AgentIntent.OPEN_EXPLORATION
    assert state.router_decision is not None
    assert state.router_decision.source == "fallback"
    event_types = [event.event_type for event in state.events]
    assert EventType.LLM_JSON_INVALID in event_types
    assert EventType.LLM_FALLBACK in event_types


def test_rule_guards_skip_llm_router_for_hi_and_confirm() -> None:
    """问候和 confirm fast-path 不应交给 LLM router 决定。"""

    client = FakeLLMClient(
        ['{"intent":"direct_analysis","confidence":0.99,"reason":"should not be used"}']
    )

    hi_state = build_initial_state(
        session_id="router-session",
        user_message="hi",
        llm_client=client,
        llm_strategy_config=LLMNodeStrategyConfig(enabled_nodes=["router"]),
    )
    confirm_state = build_initial_state(
        session_id="router-session",
        user_message="confirmed",
        command=AgentCommand.PPT_CONFIRM,
        llm_client=client,
        llm_strategy_config=LLMNodeStrategyConfig(enabled_nodes=["router"]),
    )

    assert hi_state.intent is AgentIntent.CLARIFICATION
    assert confirm_state.intent is AgentIntent.REPORT_EXPORT
    assert hi_state.router_decision.source == "rule"
    assert confirm_state.router_decision.source == "rule"
    assert client.calls == []

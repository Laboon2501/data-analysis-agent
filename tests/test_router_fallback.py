"""Router fallback and safety guard tests."""

from app.harness import LLMNodeStrategyConfig, build_initial_state
from llm.fake import FakeLLMClient
from schemas import AgentCommand, AgentIntent


def test_low_confidence_llm_router_falls_back_to_rules() -> None:
    """低置信度 LLM 路由不应覆盖规则兜底。"""

    client = FakeLLMClient(
        [
            (
                '{"intent":"schema_qa","confidence":0.2,'
                '"reason":"低置信度错误分类","needs_datasource":true}'
            )
        ]
    )

    state = build_initial_state(
        session_id="router-fallback",
        user_message="这张表有什么可以分析的吗",
        llm_client=client,
        llm_strategy_config=LLMNodeStrategyConfig(enabled_nodes=["router"]),
    )

    assert state.command is AgentCommand.EXPLORE
    assert state.intent is AgentIntent.OPEN_EXPLORATION
    assert state.router_decision is not None
    assert state.router_decision.source == "fallback"


def test_write_operation_request_never_goes_to_llm_router() -> None:
    """危险写操作请求应规则拦截，不交给 LLM router。"""

    client = FakeLLMClient(
        ['{"intent":"direct_analysis","confidence":0.99,"reason":"should not be used"}']
    )

    state = build_initial_state(
        session_id="router-fallback",
        user_message="请 drop table orders 然后分析趋势",
        llm_client=client,
        llm_strategy_config=LLMNodeStrategyConfig(enabled_nodes=["router"]),
    )

    assert state.command is AgentCommand.NONE
    assert state.intent is AgentIntent.CLARIFICATION
    assert state.router_decision is not None
    assert state.router_decision.source == "rule"
    assert client.calls == []

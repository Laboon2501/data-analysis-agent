"""LLM SQL fallback tests."""

from __future__ import annotations

from app.harness import LLMNodeStrategyConfig, build_node_strategy_map
from graphs.analysis_graph import build_analysis_graph
from llm import FakeLLMClient
from schemas import AgentState
from schemas.event import EventType
from tests.phase49_sql_helpers import CATEGORY_GMV_QUESTION, category_gmv_data_source


def test_llm_bad_profile_sql_falls_back_without_user_traceback() -> None:
    """Bad LLM SQL should fall back cleanly and keep user output free of node tracebacks."""

    client = FakeLLMClient(
        [
            (
                '{"query": "SELECT category, SUM(gmv) AS total_gmv FROM orders GROUP BY category", '
                '"used_tables": ["orders"], '
                '"used_fields": ["orders.category", "orders.gmv"], '
                '"reason": "bad profile usage"}'
            )
        ]
    )
    data_source = category_gmv_data_source()
    result = AgentState.model_validate(
        build_analysis_graph(
            data_source=data_source,
            node_strategies=build_node_strategy_map(
                LLMNodeStrategyConfig(enabled_nodes=["sql_drafter"])
            ),
            llm_client=client,
        ).invoke(
            AgentState(
                session_id="session-1",
                job_id="job-1",
                user_message=CATEGORY_GMV_QUESTION,
                datasource_id=data_source.datasource_id,
            )
        )
    )

    assert result.sql_draft is not None
    assert result.sql_draft.generation_strategy == "rule"
    assert result.sql_validation is not None and result.sql_validation.is_valid is True
    assert result.final_response_text is not None
    assert "Node '" not in result.final_response_text
    assert "traceback" not in result.final_response_text.lower()
    assert any(event.event_type is EventType.LLM_FALLBACK for event in result.events)

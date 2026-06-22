"""Analysis graph validation-routing tests."""

from __future__ import annotations

from app.harness import LLMNodeStrategyConfig, build_node_strategy_map
from graphs.analysis_graph import build_analysis_graph
from llm import FakeLLMClient
from schemas import AgentState
from schemas.event import EventType
from schemas.sql import SqlValidationStatus
from tests.phase49_sql_helpers import CATEGORY_GMV_QUESTION, category_gmv_data_source


class TrackingDataSource:
    """Datasource wrapper that records executed SQL statements."""

    def __init__(self, delegate):
        self.delegate = delegate
        self.executed_sql: list[str] = []

    @property
    def datasource_id(self):
        return self.delegate.datasource_id

    @property
    def dialect(self):
        return self.delegate.dialect

    def query(self, sql: str, limit: int | None = None, timeout_seconds: float | None = None):
        self.executed_sql.append(sql)
        return self.delegate.query(sql, limit=limit, timeout_seconds=timeout_seconds)

    def __getattr__(self, name: str):
        return getattr(self.delegate, name)


def test_invalid_sql_validation_routes_to_repair_before_execution() -> None:
    """Invalid LLM SQL should be repaired before any query reaches the datasource."""

    data_source = TrackingDataSource(category_gmv_data_source())
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
    graph = build_analysis_graph(
        data_source=data_source,
        node_strategies=build_node_strategy_map(
            LLMNodeStrategyConfig(enabled_nodes=["sql_drafter"])
        ),
        llm_client=client,
    )

    result = AgentState.model_validate(
        graph.invoke(
            AgentState(
                session_id="session-1",
                job_id="job-1",
                user_message=CATEGORY_GMV_QUESTION,
                datasource_id=data_source.datasource_id,
            )
        )
    )

    assert data_source.executed_sql == [result.sql_draft.query]
    assert "orders.category" not in data_source.executed_sql[0]
    assert "orders.gmv" not in data_source.executed_sql[0]
    assert "JOIN products" in data_source.executed_sql[0]
    assert result.sql_validation is not None
    assert result.sql_validation.status is SqlValidationStatus.VALID
    assert result.sql_result is not None
    assert result.sql_result.row_count > 0
    assert any(
        event.event_type is EventType.LLM_FALLBACK and event.node_name == "repair_sql_if_needed"
        for event in result.events
    )


def test_unrepairable_invalid_sql_stops_with_human_request_without_execution(
    sqlite_data_source,
) -> None:
    """If rule fallback cannot validate SQL, the graph should stop before execute_sql."""

    data_source = TrackingDataSource(sqlite_data_source)
    client = FakeLLMClient(
        [
            (
                '{"question": "category GMV", "kind": "top_n", '
                '"table_name": "orders", "metric_field": "orders.gmv", '
                '"time_field": null, "dimension_field": "orders.category", "top_n": 5}'
            ),
            (
                '{"steps": [{"name": "draft_sql", "objective": "Draft SQL", '
                '"required_inputs": ["database_profile"], "expected_outputs": ["sql_draft"]}], '
                '"assumptions": [], "risks": []}'
            ),
            (
                '{"query": "SELECT category, SUM(gmv) AS total_gmv FROM orders GROUP BY category", '
                '"used_tables": ["orders"], '
                '"used_fields": ["orders.category", "orders.gmv"], '
                '"reason": "bad profile usage"}'
            ),
        ]
    )
    graph = build_analysis_graph(
        data_source=data_source,
        node_strategies=build_node_strategy_map(
            LLMNodeStrategyConfig(enabled_nodes=["planner", "sql_drafter"])
        ),
        llm_client=client,
    )

    result = AgentState.model_validate(
        graph.invoke(
            AgentState(
                session_id="session-1",
                job_id="job-1",
                user_message=CATEGORY_GMV_QUESTION,
                datasource_id=data_source.datasource_id,
            )
        )
    )

    assert data_source.executed_sql == []
    assert result.needs_human is True
    assert result.human_request is not None
    assert result.sql_result is None

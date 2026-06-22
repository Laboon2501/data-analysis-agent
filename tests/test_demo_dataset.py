"""demo 数据集生成和 schema 识别测试。"""

from __future__ import annotations

from pathlib import Path

from graphs.context_manager_graph import build_context_manager_graph
from persistence import InMemoryCacheStore
from schemas.agent_state import AgentCommand, AgentIntent, AgentState
from scripts.create_demo_db import (
    create_demo_data_source,
    create_demo_db,
    inspect_demo_db,
)


def test_create_demo_db_generates_expected_tables(tmp_path) -> None:
    """create_demo_db 应可重复生成包含核心电商表的 SQLite 文件。"""

    db_path = tmp_path / "ecommerce_demo.sqlite"
    create_demo_db(db_path)
    create_demo_db(db_path)
    summary = inspect_demo_db(db_path)

    assert db_path.exists()
    assert set(summary["tables"]) == {
        "channels",
        "order_items",
        "orders",
        "products",
        "regions",
        "users",
    }
    assert summary["row_counts"]["orders"] >= 12
    assert summary["row_counts"]["order_items"] >= summary["row_counts"]["orders"]


def test_demo_csv_fixture_covers_file_datasource_smoke_fields() -> None:
    """demo CSV fixture should cover time, money, quantity, category, and region/channel."""

    csv_path = Path("demo/ecommerce_orders_demo.csv")
    text = csv_path.read_text(encoding="utf-8")
    header = text.splitlines()[0].split(",")

    assert csv_path.exists()
    assert header == ["order_month", "gmv", "quantity", "category", "region", "channel"]
    assert len(text.splitlines()) >= 4


def test_demo_datasource_schema_is_profiled(tmp_path) -> None:
    """demo datasource 应能被 Context Manager 识别出时间、指标和维度字段。"""

    db_path = tmp_path / "ecommerce_demo.sqlite"
    data_source = create_demo_data_source(db_path=db_path)
    state = AgentState(
        session_id="demo-test-session",
        job_id="demo-test-job",
        user_message="Profile the ecommerce demo database",
        command=AgentCommand.PROFILE,
        intent=AgentIntent.CONTEXT_MANAGER,
        datasource_id=data_source.datasource_id,
    )

    result = AgentState.model_validate(
        build_context_manager_graph(
            data_source=data_source,
            cache_store=InMemoryCacheStore(),
        ).invoke(state)
    )

    assert result.database_profile is not None
    assert {table.name for table in result.database_profile.tables} >= {
        "orders",
        "order_items",
        "products",
        "users",
    }
    assert "orders.order_month" in result.database_profile.time_fields
    assert "orders.gmv" in result.database_profile.candidate_metrics
    assert "orders.category" in result.database_profile.candidate_dimensions
    assert "orders.region_name" in result.database_profile.candidate_dimensions

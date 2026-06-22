"""Tests for guarded SQL tools and ToolRegistry integration."""

import pytest

from datasource import SQLAlchemyDataSource
from schemas import DatabaseProfile, QueryResult
from tools import build_datasource_tool_registry
from tools.sql_tools import query_data


def test_query_data_runs_guarded_select(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """query_data should return QueryResult for safe SELECT statements."""

    result = query_data(
        sqlite_data_source,
        "SELECT id, revenue FROM orders ORDER BY id",
        limit=2,
        timeout_seconds=1,
    )

    assert isinstance(result, QueryResult)
    assert result.row_count == 2
    assert result.truncated is True
    assert [row["revenue"] for row in result.rows] == [100.0, 120.0]


def test_query_data_allows_with_select(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """WITH SELECT should pass guard and physical table validation."""

    result = query_data(
        sqlite_data_source,
        """
        WITH monthly AS (
            SELECT month, revenue FROM orders
        )
        SELECT month, revenue FROM monthly ORDER BY month
        """,
    )

    assert result.row_count == 3


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE orders SET revenue = 0",
        "DELETE FROM orders",
        "DROP TABLE orders",
    ],
)
def test_query_data_rejects_illegal_write_sql(
    sqlite_data_source: SQLAlchemyDataSource,
    sql: str,
) -> None:
    """query_data must reject write SQL before datasource execution."""

    with pytest.raises(ValueError):
        query_data(sqlite_data_source, sql)

    assert query_data(sqlite_data_source, "SELECT COUNT(*) AS count FROM orders").rows == [
        {"count": 3}
    ]


def test_query_data_rejects_unknown_table(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """Unknown table references should be rejected before execution."""

    with pytest.raises(ValueError, match="Unknown table"):
        query_data(sqlite_data_source, "SELECT id FROM missing")


def test_query_data_rejects_unknown_field(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """Unknown column references should be rejected before execution."""

    with pytest.raises(ValueError, match="Unknown column"):
        query_data(sqlite_data_source, "SELECT missing_field FROM orders")


def test_datasource_tool_registry_registers_categories_and_node_permissions(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """Datasource tools should be category registered and node scoped."""

    registry = build_datasource_tool_registry(
        sqlite_data_source,
        node_tool_categories={
            "context_node": ("schema",),
            "sql_node": ("sql",),
        },
    )

    assert [tool.name for tool in registry.get_tools_by_category("schema")] == [
        "get_schema",
        "get_table_detail",
        "sample_table",
    ]
    assert [tool.name for tool in registry.get_tools_by_category("sql")] == ["query_data"]
    assert [tool.name for tool in registry.get_allowed_tools("context_node")] == [
        "get_schema",
        "get_table_detail",
        "sample_table",
    ]
    assert [tool.name for tool in registry.get_allowed_tools("sql_node")] == ["query_data"]

    schema = registry.get_allowed_handlers("context_node")["get_schema"]()

    assert isinstance(schema, DatabaseProfile)
    assert "query_data" not in registry.get_allowed_handlers("context_node")

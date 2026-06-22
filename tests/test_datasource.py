"""Tests for SQLAlchemy datasource introspection and read-only query support."""

import pytest

from datasource import SQLAlchemyDataSource
from schemas import DatabaseProfile, QueryResult, TableProfile


def test_datasource_lists_tables(sqlite_data_source: SQLAlchemyDataSource) -> None:
    """Datasource should list reflected SQLite tables."""

    assert sqlite_data_source.list_tables() == ["customers", "orders"]
    assert sqlite_data_source.has_table("orders") is True
    assert sqlite_data_source.has_table("missing") is False


def test_datasource_get_schema_returns_database_profile(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """Schema introspection should return DatabaseProfile, not loose dicts."""

    profile = sqlite_data_source.get_schema()

    assert isinstance(profile, DatabaseProfile)
    assert profile.datasource_id == "test-sqlite"
    assert {table.name for table in profile.tables} == {"customers", "orders"}
    assert profile.schema_hash


def test_datasource_get_table_detail_includes_columns_and_row_count(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """Table detail should expose columns, primary keys, and row count."""

    detail = sqlite_data_source.get_table_detail("orders")

    assert isinstance(detail, TableProfile)
    assert detail.row_count == 3
    assert detail.primary_key == ["id"]
    assert {column.name for column in detail.columns} == {"id", "customer_id", "month", "revenue"}
    assert sqlite_data_source.has_column("orders", "revenue") is True
    assert sqlite_data_source.has_column("orders", "missing") is False


def test_datasource_unknown_table_raises(sqlite_data_source: SQLAlchemyDataSource) -> None:
    """Unknown tables should fail before query construction."""

    with pytest.raises(ValueError, match="Unknown table"):
        sqlite_data_source.get_table_detail("missing")


def test_datasource_sample_rows_returns_query_result(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """Sample rows should return bounded QueryResult data."""

    result = sqlite_data_source.sample_rows("orders", limit=2)

    assert isinstance(result, QueryResult)
    assert result.row_count == 2
    assert result.truncated is True
    assert {column.name for column in result.columns} == {"id", "customer_id", "month", "revenue"}


def test_datasource_query_supports_limit_placeholder(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """Datasource query should support row limiting without adding analysis behavior."""

    result = sqlite_data_source.query("SELECT id, revenue FROM orders ORDER BY id", limit=2)

    assert result.row_count == 2
    assert result.truncated is True
    assert [row["id"] for row in result.rows] == [1, 2]

"""Tests for datasource-backed schema tools."""

import pytest

from datasource import SQLAlchemyDataSource
from schemas import DatabaseProfile, QueryResult, TableProfile
from tools.schema_tools import get_schema, get_table_detail, sample_table


def test_get_schema_tool_returns_database_profile(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """get_schema should return the datasource DatabaseProfile."""

    profile = get_schema(sqlite_data_source)

    assert isinstance(profile, DatabaseProfile)
    assert {table.name for table in profile.tables} == {"customers", "orders"}


def test_get_table_detail_tool_returns_table_profile(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """get_table_detail should return TableProfile."""

    detail = get_table_detail(sqlite_data_source, "customers")

    assert isinstance(detail, TableProfile)
    assert detail.row_count == 2
    assert {column.name for column in detail.columns} == {"id", "region"}


def test_get_table_detail_tool_rejects_unknown_table(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """Unknown tables should surface clear datasource errors."""

    with pytest.raises(ValueError, match="Unknown table"):
        get_table_detail(sqlite_data_source, "missing")


def test_sample_table_tool_returns_query_result(
    sqlite_data_source: SQLAlchemyDataSource,
) -> None:
    """sample_table should return QueryResult."""

    result = sample_table(sqlite_data_source, "orders", limit=1)

    assert isinstance(result, QueryResult)
    assert result.row_count == 1
    assert result.truncated is True

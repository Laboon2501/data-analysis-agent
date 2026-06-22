"""Schema tools backed by a datasource interface."""

from __future__ import annotations

from datasource.base import DataSource
from schemas.database_profile import DatabaseProfile, TableProfile
from schemas.query_result import QueryResult


def get_schema(data_source: DataSource) -> DatabaseProfile:
    """Return datasource schema as a DatabaseProfile."""

    return data_source.get_schema()


def get_table_detail(data_source: DataSource, table_name: str) -> TableProfile:
    """Return table metadata as a TableProfile."""

    return data_source.get_table_detail(table_name)


def sample_table(data_source: DataSource, table_name: str, limit: int = 5) -> QueryResult:
    """Return bounded table samples as a QueryResult."""

    return data_source.sample_rows(table_name, limit=limit)

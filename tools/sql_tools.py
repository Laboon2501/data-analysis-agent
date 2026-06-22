"""Read-only SQL tools backed by SQL guard and datasource execution."""

from __future__ import annotations

from datasource.base import DataSource
from guards.sql_guard import SqlGuardResult, validate_select_only_sql
from schemas.query_result import QueryResult


def query_data(
    data_source: DataSource,
    sql: str,
    *,
    limit: int | None = None,
    timeout_seconds: float | None = None,
) -> QueryResult:
    """Validate and execute read-only SQL against a datasource."""

    guard_result = validate_select_only_sql(sql, dialect=data_source.dialect)
    _raise_for_guard_failure(guard_result)
    _validate_sql_references(data_source, guard_result)
    return data_source.query(sql, limit=limit, timeout_seconds=timeout_seconds)


def _raise_for_guard_failure(guard_result: SqlGuardResult) -> None:
    """Raise a clear exception for disallowed SQL."""

    if not guard_result.is_allowed:
        raise ValueError("; ".join(guard_result.errors) or "SQL is not allowed.")


def _validate_sql_references(data_source: DataSource, guard_result: SqlGuardResult) -> None:
    """Validate referenced physical tables and columns before execution."""

    referenced_tables = guard_result.referenced_tables
    for table_name in referenced_tables:
        if not data_source.has_table(table_name):
            raise ValueError(f"Unknown table referenced by SQL: {table_name}")

    for column_name in guard_result.referenced_columns:
        if referenced_tables and not any(
            data_source.has_column(table_name, column_name) for table_name in referenced_tables
        ):
            raise ValueError(f"Unknown column referenced by SQL: {column_name}")

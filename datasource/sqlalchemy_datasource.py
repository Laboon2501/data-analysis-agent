"""SQLAlchemy datasource for relational schema inspection and read-only queries."""

from __future__ import annotations

import json
from collections.abc import Iterable
from hashlib import sha256
from time import perf_counter
from typing import Any

from sqlalchemy import Engine, MetaData, Table, create_engine, func, inspect, select, text
from sqlalchemy.engine import RowMapping

from datasource.base import DataSource
from schemas.database_profile import (
    DatabaseProfile,
    FieldProfile,
    ProfileStatus,
    TableProfile,
)
from schemas.query_result import QueryColumn, QueryResult


class SQLAlchemyDataSource(DataSource):
    """SQLAlchemy-backed datasource for safe Phase 3 introspection and querying."""

    def __init__(
        self,
        *,
        datasource_id: str,
        engine: Engine | None = None,
        url: str | None = None,
        dialect: str | None = None,
    ) -> None:
        if engine is None and url is None:
            raise ValueError("Either engine or url must be provided.")
        self._engine = engine or create_engine(url or "")
        self._datasource_id = datasource_id
        self._dialect = dialect or self._engine.dialect.name

    @property
    def datasource_id(self) -> str:
        """Stable datasource identifier."""

        return self._datasource_id

    @property
    def dialect(self) -> str:
        """SQL dialect label."""

        return self._dialect

    def list_tables(self) -> list[str]:
        """Return table names visible to SQLAlchemy inspector."""

        return sorted(inspect(self._engine).get_table_names())

    def has_table(self, table_name: str) -> bool:
        """Return whether a table exists."""

        return table_name in self.list_tables()

    def has_column(self, table_name: str, column_name: str) -> bool:
        """Return whether a column exists in a table."""

        if not self.has_table(table_name):
            return False
        return any(
            column.name == column_name for column in self.get_table_detail(table_name).columns
        )

    def get_schema(self) -> DatabaseProfile:
        """Build a clean database profile from reflected table metadata."""

        tables = [self.get_table_detail(table_name) for table_name in self.list_tables()]
        schema_payload = [
            {
                "name": table.name,
                "columns": [
                    {
                        "name": column.name,
                        "data_type": column.data_type,
                        "nullable": column.nullable,
                    }
                    for column in table.columns
                ],
                "primary_key": table.primary_key,
            }
            for table in tables
        ]
        schema_hash = sha256(
            json.dumps(schema_payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        return DatabaseProfile(
            datasource_id=self.datasource_id,
            schema_hash=schema_hash,
            status=ProfileStatus.PENDING,
            tables=tables,
        )

    def get_table_detail(self, table_name: str) -> TableProfile:
        """Return table metadata and row count."""

        self._ensure_table_exists(table_name)
        inspector = inspect(self._engine)
        columns = [
            FieldProfile(
                name=column["name"],
                data_type=str(column["type"]),
                nullable=column.get("nullable"),
            )
            for column in inspector.get_columns(table_name)
        ]
        primary_key = inspector.get_pk_constraint(table_name).get("constrained_columns") or []
        return TableProfile(
            name=table_name,
            row_count=self.count_rows(table_name),
            columns=columns,
            primary_key=list(primary_key),
        )

    def count_rows(self, table_name: str) -> int:
        """Return row count for a reflected table."""

        table = self._reflect_table(table_name)
        with self._engine.connect() as connection:
            return int(connection.execute(select(func.count()).select_from(table)).scalar_one())

    def sample_rows(self, table_name: str, limit: int = 5) -> QueryResult:
        """Return sample rows from a table as a QueryResult."""

        self._validate_limit(limit)
        table = self._reflect_table(table_name)
        statement = select(table).limit(limit)
        started_at = perf_counter()
        with self._engine.connect() as connection:
            rows = [dict(row) for row in connection.execute(statement).mappings().all()]
        execution_ms = (perf_counter() - started_at) * 1000
        return QueryResult(
            sql=str(statement),
            columns=[
                QueryColumn(name=column.name, data_type=str(column.type))
                for column in table.columns
            ],
            rows=rows,
            row_count=len(rows),
            truncated=len(rows) == limit and self.count_rows(table_name) > limit,
            execution_ms=execution_ms,
        )

    def query(
        self,
        sql: str,
        limit: int | None = None,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        """Execute a read-only SQL string after higher-level guard validation."""

        self._validate_optional_limit(limit)
        self._validate_optional_timeout(timeout_seconds)
        started_at = perf_counter()
        with self._engine.connect() as connection:
            result = connection.execute(text(sql))
            rows = self._fetch_limited_rows(result.mappings(), limit)
            columns = [
                QueryColumn(name=column_name, data_type="unknown") for column_name in result.keys()
            ]
        execution_ms = (perf_counter() - started_at) * 1000
        returned_rows = rows[:limit] if limit is not None else rows
        return QueryResult(
            sql=sql,
            columns=columns,
            rows=returned_rows,
            row_count=len(returned_rows),
            truncated=limit is not None and len(rows) > limit,
            execution_ms=execution_ms,
        )

    def _reflect_table(self, table_name: str) -> Table:
        """Reflect a table after verifying it exists."""

        self._ensure_table_exists(table_name)
        return Table(table_name, MetaData(), autoload_with=self._engine)

    def _ensure_table_exists(self, table_name: str) -> None:
        """Raise a clear error when a table is unknown."""

        if not self.has_table(table_name):
            raise ValueError(f"Unknown table: {table_name}")

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1.")

    @classmethod
    def _validate_optional_limit(cls, limit: int | None) -> None:
        if limit is not None:
            cls._validate_limit(limit)

    @staticmethod
    def _validate_optional_timeout(timeout_seconds: float | None) -> None:
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive when provided.")

    @staticmethod
    def _fetch_limited_rows(rows: Iterable[RowMapping], limit: int | None) -> list[dict[str, Any]]:
        """Fetch rows with one extra item when a limit is provided to detect truncation."""

        max_rows = None if limit is None else limit + 1
        fetched_rows: list[dict[str, Any]] = []
        for row in rows:
            fetched_rows.append(dict(row))
            if max_rows is not None and len(fetched_rows) >= max_rows:
                break
        return fetched_rows

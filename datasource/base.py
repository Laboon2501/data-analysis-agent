"""Datasource protocol used by tools and future Context Manager nodes."""

from __future__ import annotations

from typing import Protocol

from schemas.database_profile import DatabaseProfile, TableProfile
from schemas.query_result import QueryResult


class DataSource(Protocol):
    """Minimal relational datasource interface for Phase 3 tools."""

    @property
    def datasource_id(self) -> str:
        """Stable datasource identifier."""

    @property
    def dialect(self) -> str:
        """SQL dialect label used by guards and parsing."""

    def list_tables(self) -> list[str]:
        """Return available table names."""

    def has_table(self, table_name: str) -> bool:
        """Return whether a table exists."""

    def has_column(self, table_name: str, column_name: str) -> bool:
        """Return whether a column exists in a table."""

    def get_schema(self) -> DatabaseProfile:
        """Return a database profile with table and field metadata."""

    def get_table_detail(self, table_name: str) -> TableProfile:
        """Return detailed table metadata."""

    def count_rows(self, table_name: str) -> int:
        """Return row count for a table."""

    def sample_rows(self, table_name: str, limit: int = 5) -> QueryResult:
        """Return bounded sample rows for one table."""

    def query(
        self,
        sql: str,
        limit: int | None = None,
        timeout_seconds: float | None = None,
    ) -> QueryResult:
        """Execute a validated read-only query and return tabular results."""

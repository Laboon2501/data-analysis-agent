"""Query result schemas used after safe SQL execution."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import Field

from schemas._base import StrictBaseModel


class QueryColumn(StrictBaseModel):
    """Column metadata returned with a query result."""

    name: str
    data_type: str
    semantic_type: str | None = None


class QueryResult(StrictBaseModel):
    """Bounded tabular result returned by a SQL execution tool."""

    result_id: str = Field(default_factory=lambda: str(uuid4()))
    sql: str
    columns: list[QueryColumn] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = Field(default=0, ge=0)
    truncated: bool = False
    execution_ms: float | None = Field(default=None, ge=0)

"""Schema QA result contracts for datasource field inspection answers."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from schemas._base import StrictBaseModel
from schemas.database_profile import FieldSemanticType, TableRole


class SchemaFieldSummary(StrictBaseModel):
    """Bounded field metadata shown to users for schema questions."""

    table_name: str
    field_name: str
    qualified_name: str
    data_type: str
    semantic_type: FieldSemanticType = FieldSemanticType.UNKNOWN
    sample_values: list[Any] = Field(default_factory=list)
    description: str | None = None
    is_metric_candidate: bool = False
    is_dimension_candidate: bool = False


class SchemaTableSummary(StrictBaseModel):
    """Bounded table metadata shown to users for schema questions."""

    table_name: str
    row_count: int | None = Field(default=None, ge=0)
    role: TableRole = TableRole.UNKNOWN
    fields: list[SchemaFieldSummary] = Field(default_factory=list)


class SchemaQAResult(StrictBaseModel):
    """Structured output for schema QA / data inspection graph."""

    question: str
    datasource_id: str
    answer: str
    tables: list[SchemaTableSummary] = Field(default_factory=list)
    candidate_metrics: list[str] = Field(default_factory=list)
    candidate_dimensions: list[str] = Field(default_factory=list)
    analysis_suggestions: list[str] = Field(default_factory=list)

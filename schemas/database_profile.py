"""Database profiling contracts produced by the Context Manager graph."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from schemas._base import StrictBaseModel, utc_now


class ProfileStatus(StrEnum):
    """Lifecycle status for a database profile."""

    MISSING = "missing"
    PENDING = "pending"
    NEEDS_CONFIRMATION = "needs_confirmation"
    CONFIRMED = "confirmed"
    CACHED = "cached"
    FAILED = "failed"


class TableRole(StrEnum):
    """High-level role inferred for a table."""

    UNKNOWN = "unknown"
    FACT = "fact"
    DIMENSION = "dimension"
    BRIDGE = "bridge"
    LOOKUP = "lookup"


class FieldSemanticType(StrEnum):
    """Narrow semantic label for a database field."""

    UNKNOWN = "unknown"
    IDENTIFIER = "identifier"
    MEASURE = "measure"
    DIMENSION = "dimension"
    DATETIME = "datetime"
    CATEGORICAL = "categorical"
    TEXT = "text"
    CURRENCY = "currency"


class FieldProfile(StrictBaseModel):
    """Column-level metadata stored after profiling."""

    name: str
    data_type: str
    nullable: bool | None = None
    sample_values: list[Any] = Field(default_factory=list)
    semantic_type: FieldSemanticType = FieldSemanticType.UNKNOWN
    description: str | None = None
    is_metric_candidate: bool = False
    is_dimension_candidate: bool = False


class TableProfile(StrictBaseModel):
    """Table-level metadata stored in a database profile."""

    name: str
    row_count: int | None = Field(default=None, ge=0)
    role: TableRole = TableRole.UNKNOWN
    columns: list[FieldProfile] = Field(default_factory=list)
    primary_key: list[str] = Field(default_factory=list)


class TableRelationship(StrictBaseModel):
    """Relationship candidate between two tables."""

    from_table: str
    from_column: str
    to_table: str
    to_column: str
    relationship_type: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class AmbiguousField(StrictBaseModel):
    """Field whose meaning needs explicit confirmation before analysis."""

    table_name: str
    field_name: str
    candidate_meanings: list[str] = Field(default_factory=list)
    reason: str


class ConfirmedBusinessRule(StrictBaseModel):
    """Business rule or metric definition confirmed by a user."""

    name: str
    description: str
    confirmed_by: str | None = None
    source: str | None = None


class DatabaseProfile(StrictBaseModel):
    """Clean database profile consumed by downstream analysis graphs."""

    datasource_id: str
    schema_hash: str
    profile_version: int = Field(default=1, ge=1)
    status: ProfileStatus = ProfileStatus.PENDING
    tables: list[TableProfile] = Field(default_factory=list)
    relationships: list[TableRelationship] = Field(default_factory=list)
    time_fields: list[str] = Field(default_factory=list)
    metric_fields: list[str] = Field(default_factory=list)
    dimension_fields: list[str] = Field(default_factory=list)
    candidate_metrics: list[str] = Field(default_factory=list)
    candidate_dimensions: list[str] = Field(default_factory=list)
    ambiguous_fields: list[AmbiguousField] = Field(default_factory=list)
    confirmed_business_rules: list[ConfirmedBusinessRule] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

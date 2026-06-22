"""Rule-based Context Manager nodes for building DatabaseProfile."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from datasource.base import DataSource
from persistence.interfaces import CacheStore
from schemas.agent_state import AgentState
from schemas.database_profile import (
    AmbiguousField,
    DatabaseProfile,
    FieldProfile,
    FieldSemanticType,
    ProfileStatus,
    TableProfile,
    TableRelationship,
    TableRole,
)
from schemas.human import HumanRequest, HumanRequestType

SAMPLE_ROW_LIMIT = 5


def profile_cache_key(datasource_id: str, schema_hash: str) -> str:
    """Build a stable cache key for a datasource schema profile."""

    return f"profile:{datasource_id}:{schema_hash}"


def read_schema(
    state: AgentState,
    *,
    data_source: DataSource,
    cache_store: CacheStore | None = None,
) -> AgentState:
    """Read datasource schema and hydrate profile from cache when available."""

    profile = data_source.get_schema()
    state.datasource_id = profile.datasource_id

    cached_profile = None
    if cache_store is not None:
        cached_profile = cache_store.get(
            profile_cache_key(profile.datasource_id, profile.schema_hash)
        )

    if isinstance(cached_profile, DatabaseProfile):
        profile = cached_profile.model_copy(deep=True)
        profile.status = ProfileStatus.CACHED
        state.profile_status = ProfileStatus.CACHED
    else:
        state.profile_status = ProfileStatus.PENDING

    state.database_profile = profile
    return state


def sample_tables(state: AgentState, *, data_source: DataSource) -> AgentState:
    """Attach bounded sample values to profile fields."""

    if _is_cached(state):
        return state
    profile = _require_profile(state)
    sampled_tables = []
    for table in profile.tables:
        sample = data_source.sample_rows(table.name, limit=SAMPLE_ROW_LIMIT)
        sampled_tables.append(_table_with_sample_values(table, sample.rows))
    state.database_profile = profile.model_copy(update={"tables": sampled_tables})
    return state


def infer_table_roles(state: AgentState) -> AgentState:
    """Infer coarse table roles from columns and candidate measures."""

    if _is_cached(state):
        return state
    profile = _require_profile(state)
    tables = []
    for table in profile.tables:
        metric_like_columns = [
            column
            for column in table.columns
            if _is_numeric_type(column.data_type) and not _is_identifier_name(column.name)
        ]
        foreign_key_like_columns = [
            column
            for column in table.columns
            if column.name.endswith("_id") and column.name != "id"
        ]
        if metric_like_columns or foreign_key_like_columns:
            role = TableRole.FACT
        elif table.primary_key:
            role = TableRole.DIMENSION
        else:
            role = TableRole.UNKNOWN
        tables.append(table.model_copy(update={"role": role}))
    state.database_profile = profile.model_copy(update={"tables": tables})
    return state


def infer_field_semantics(state: AgentState) -> AgentState:
    """Infer field semantics using deterministic name and type rules."""

    if _is_cached(state):
        return state
    profile = _require_profile(state)
    tables = [
        table.model_copy(
            update={
                "columns": [
                    _field_with_semantics(column, table.primary_key) for column in table.columns
                ]
            }
        )
        for table in profile.tables
    ]
    state.database_profile = profile.model_copy(update={"tables": tables})
    return state


def infer_relationships(state: AgentState) -> AgentState:
    """Infer relationships from primary keys and *_id naming conventions."""

    if _is_cached(state):
        return state
    profile = _require_profile(state)
    table_names = {table.name for table in profile.tables}
    relationships: list[TableRelationship] = []
    for table in profile.tables:
        for column in table.columns:
            if not column.name.endswith("_id") or column.name == "id":
                continue
            target_stem = column.name.removesuffix("_id")
            target_table = _resolve_table_name(target_stem, table_names)
            if target_table is None:
                continue
            relationships.append(
                TableRelationship(
                    from_table=table.name,
                    from_column=column.name,
                    to_table=target_table,
                    to_column="id",
                    relationship_type="many_to_one",
                    confidence=0.8,
                )
            )
    state.database_profile = profile.model_copy(update={"relationships": relationships})
    return state


def generate_candidate_metrics(state: AgentState) -> AgentState:
    """Generate candidate metric field references from inferred semantics."""

    if _is_cached(state):
        return state
    profile = _require_profile(state)
    metric_fields = [
        *_qualified_fields(profile, FieldSemanticType.MEASURE),
        *_qualified_fields(profile, FieldSemanticType.CURRENCY),
    ]
    state.database_profile = profile.model_copy(
        update={
            "metric_fields": metric_fields,
            "candidate_metrics": metric_fields,
        }
    )
    return state


def generate_candidate_dimensions(state: AgentState) -> AgentState:
    """Generate candidate dimension and time field references."""

    if _is_cached(state):
        return state
    profile = _require_profile(state)
    dimension_fields = [
        *_qualified_fields(profile, FieldSemanticType.DIMENSION),
        *_qualified_fields(profile, FieldSemanticType.CATEGORICAL),
    ]
    time_fields = _qualified_fields(profile, FieldSemanticType.DATETIME)
    state.database_profile = profile.model_copy(
        update={
            "dimension_fields": dimension_fields,
            "candidate_dimensions": [*dimension_fields, *time_fields],
            "time_fields": time_fields,
        }
    )
    return state


def detect_ambiguity(state: AgentState) -> AgentState:
    """Create a HumanRequest when fields remain semantically ambiguous."""

    if _is_cached(state):
        return state
    profile = _require_profile(state)
    ambiguous_fields = [
        AmbiguousField(
            table_name=table.name,
            field_name=column.name,
            candidate_meanings=["identifier", "dimension", "metric"],
            reason="Field meaning could not be inferred from deterministic rules.",
        )
        for table in profile.tables
        for column in table.columns
        if column.semantic_type is FieldSemanticType.UNKNOWN
    ]
    profile_status = (
        ProfileStatus.NEEDS_CONFIRMATION if ambiguous_fields else ProfileStatus.CONFIRMED
    )
    state.database_profile = profile.model_copy(
        update={
            "ambiguous_fields": ambiguous_fields,
            "status": profile_status,
        }
    )
    state.profile_status = profile_status
    state.needs_human = bool(ambiguous_fields)
    if ambiguous_fields:
        state.human_request = HumanRequest(
            request_type=HumanRequestType.FIELD_SEMANTIC_AMBIGUITY,
            prompt="Please confirm ambiguous field semantics before analysis.",
            context={
                "ambiguous_fields": [
                    {
                        "table_name": field.table_name,
                        "field_name": field.field_name,
                        "candidate_meanings": field.candidate_meanings,
                    }
                    for field in ambiguous_fields
                ]
            },
        )
    return state


def save_profile_cache(
    state: AgentState,
    *,
    cache_store: CacheStore,
) -> AgentState:
    """Persist the generated DatabaseProfile in cache."""

    if _is_cached(state):
        return state
    profile = _require_profile(state)
    cache_store.set(profile_cache_key(profile.datasource_id, profile.schema_hash), profile)
    return state


def _require_profile(state: AgentState) -> DatabaseProfile:
    """Return the active profile or raise a clear graph wiring error."""

    if state.database_profile is None:
        raise ValueError("AgentState.database_profile is required for context node execution.")
    return state.database_profile


def _is_cached(state: AgentState) -> bool:
    """Return whether state was hydrated from profile cache."""

    return state.profile_status is ProfileStatus.CACHED


def _table_with_sample_values(table: TableProfile, rows: list[dict[str, Any]]) -> TableProfile:
    """Attach column sample values from sampled rows."""

    return table.model_copy(
        update={
            "columns": [
                column.model_copy(
                    update={
                        "sample_values": _sample_values_for_column(column.name, rows),
                    }
                )
                for column in table.columns
            ]
        }
    )


def _sample_values_for_column(column_name: str, rows: list[dict[str, Any]]) -> list[Any]:
    """Collect unique non-null sample values for a column."""

    values: list[Any] = []
    for row in rows:
        value = row.get(column_name)
        if value is not None and value not in values:
            values.append(value)
    return values


def _field_with_semantics(column: FieldProfile, primary_key: list[str]) -> FieldProfile:
    """Return a field with deterministic semantic and candidate flags."""

    semantic_type = _infer_field_semantic_type(column, primary_key)
    return column.model_copy(
        update={
            "semantic_type": semantic_type,
            "is_metric_candidate": semantic_type is FieldSemanticType.MEASURE,
            "is_dimension_candidate": semantic_type
            in {
                FieldSemanticType.DIMENSION,
                FieldSemanticType.CATEGORICAL,
                FieldSemanticType.DATETIME,
            },
        }
    )


def _infer_field_semantic_type(
    column: FieldProfile,
    primary_key: list[str],
) -> FieldSemanticType:
    """Infer field semantic type from name and physical data type."""

    name = column.name.lower()
    if column.name in primary_key or name == "id" or name.endswith("_id"):
        return FieldSemanticType.IDENTIFIER
    if any(token in name for token in ("date", "time", "month", "year", "week", "day")):
        return FieldSemanticType.DATETIME
    if _is_numeric_type(column.data_type):
        if any(
            token in name for token in ("amount", "revenue", "sales", "price", "cost", "profit")
        ):
            return FieldSemanticType.CURRENCY
        return FieldSemanticType.MEASURE
    if _is_text_type(column.data_type):
        if any(
            token in name for token in ("name", "region", "country", "city", "category", "type")
        ):
            return FieldSemanticType.CATEGORICAL
        return FieldSemanticType.DIMENSION
    return FieldSemanticType.UNKNOWN


def _qualified_fields(profile: DatabaseProfile, semantic_type: FieldSemanticType) -> list[str]:
    """Return table-qualified fields with the requested semantic type."""

    return [
        f"{table.name}.{column.name}"
        for table in profile.tables
        for column in table.columns
        if column.semantic_type is semantic_type
    ]


def _resolve_table_name(target_stem: str, table_names: Iterable[str]) -> str | None:
    """Resolve a target table from a foreign-key-like column stem."""

    candidates = (target_stem, f"{target_stem}s")
    for candidate in candidates:
        if candidate in table_names:
            return candidate
    return None


def _is_identifier_name(name: str) -> bool:
    """Return whether a field name looks like an identifier."""

    lowered_name = name.lower()
    return lowered_name == "id" or lowered_name.endswith("_id")


def _is_numeric_type(data_type: str) -> bool:
    """Return whether a physical type is numeric."""

    normalized = data_type.lower()
    return any(
        token in normalized for token in ("int", "real", "float", "double", "numeric", "decimal")
    )


def _is_text_type(data_type: str) -> bool:
    """Return whether a physical type is textual."""

    normalized = data_type.lower()
    return any(token in normalized for token in ("text", "char", "string", "varchar"))

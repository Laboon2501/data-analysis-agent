"""Tests for the rule-based Context Manager graph."""

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from datasource import SQLAlchemyDataSource
from graphs.context_manager_graph import build_context_manager_graph
from nodes.context_nodes import profile_cache_key
from persistence import InMemoryCacheStore
from schemas import (
    AgentState,
    FieldSemanticType,
    HumanRequestType,
    ProfileStatus,
    TableRole,
)


def _run_context_graph(data_source, cache_store=None) -> AgentState:
    """Invoke the Context Manager graph and validate the returned state."""

    graph = build_context_manager_graph(data_source=data_source, cache_store=cache_store)
    result = graph.invoke(
        AgentState(
            session_id="session-1",
            job_id="job-1",
            user_message="profile datasource",
            datasource_id=data_source.datasource_id,
        )
    )
    return AgentState.model_validate(result)


def test_context_manager_graph_generates_database_profile(sqlite_data_source) -> None:
    """The graph should build and attach a clean DatabaseProfile."""

    state = _run_context_graph(sqlite_data_source, InMemoryCacheStore())
    profile = state.database_profile

    assert profile is not None
    assert state.profile_status is ProfileStatus.CONFIRMED
    assert profile.status is ProfileStatus.CONFIRMED
    assert profile.datasource_id == "test-sqlite"
    assert profile.schema_hash
    assert {table.name for table in profile.tables} == {"customers", "orders"}


def test_context_manager_infers_table_roles_metrics_dimensions_and_relationships(
    sqlite_data_source,
) -> None:
    """Rule-based profiling should infer roles, fields, and FK-like relationships."""

    state = _run_context_graph(sqlite_data_source, InMemoryCacheStore())
    profile = state.database_profile
    assert profile is not None

    roles_by_table = {table.name: table.role for table in profile.tables}
    assert roles_by_table == {
        "customers": TableRole.DIMENSION,
        "orders": TableRole.FACT,
    }
    assert "orders.revenue" in profile.candidate_metrics
    assert "customers.region" in profile.candidate_dimensions
    assert "orders.month" in profile.time_fields
    assert profile.relationships[0].from_table == "orders"
    assert profile.relationships[0].from_column == "customer_id"
    assert profile.relationships[0].to_table == "customers"


def test_context_manager_attaches_sample_values(sqlite_data_source) -> None:
    """sample_tables should enrich field profiles with bounded sample values."""

    state = _run_context_graph(sqlite_data_source, InMemoryCacheStore())
    profile = state.database_profile
    assert profile is not None
    orders = next(table for table in profile.tables if table.name == "orders")
    revenue = next(column for column in orders.columns if column.name == "revenue")

    assert revenue.semantic_type is FieldSemanticType.CURRENCY
    assert revenue.sample_values == [100.0, 120.0, 90.0]


def test_context_manager_detects_ambiguity_and_sets_human_request() -> None:
    """Unknown field semantics should produce a HumanRequest placeholder."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE event_payloads (
                    id INTEGER PRIMARY KEY,
                    payload BLOB
                )
                """
            )
        )
        connection.execute(text("INSERT INTO event_payloads (id, payload) VALUES (1, x'0102')"))
    data_source = SQLAlchemyDataSource(
        datasource_id="ambiguous-sqlite",
        engine=engine,
        dialect="sqlite",
    )

    state = _run_context_graph(data_source, InMemoryCacheStore())
    profile = state.database_profile

    assert profile is not None
    assert state.profile_status is ProfileStatus.NEEDS_CONFIRMATION
    assert state.needs_human is True
    assert state.human_request is not None
    assert state.human_request.request_type is HumanRequestType.FIELD_SEMANTIC_AMBIGUITY
    assert profile.ambiguous_fields[0].table_name == "event_payloads"
    assert profile.ambiguous_fields[0].field_name == "payload"


def test_context_manager_uses_profile_cache_on_schema_hash_hit(sqlite_data_source) -> None:
    """A second run with the same schema should hydrate DatabaseProfile from cache."""

    cache_store = InMemoryCacheStore()
    first_state = _run_context_graph(sqlite_data_source, cache_store)
    assert first_state.database_profile is not None
    cache_key = profile_cache_key(
        first_state.database_profile.datasource_id,
        first_state.database_profile.schema_hash,
    )
    assert cache_store.get(cache_key) is not None

    second_state = _run_context_graph(sqlite_data_source, cache_store)

    assert second_state.database_profile is not None
    assert second_state.profile_status is ProfileStatus.CACHED
    assert second_state.database_profile.status is ProfileStatus.CACHED
    assert second_state.database_profile.schema_hash == first_state.database_profile.schema_hash

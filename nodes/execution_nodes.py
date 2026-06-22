"""Execution nodes for guarded read-only SQL."""

from __future__ import annotations

from datasource.base import DataSource
from schemas.agent_state import AgentState
from schemas.sql import SqlValidationStatus
from tools.sql_tools import query_data


def execute_sql(
    state: AgentState,
    *,
    data_source: DataSource,
    limit: int | None = 100,
    timeout_seconds: float | None = None,
) -> AgentState:
    """Execute validated read-only SQL through the SQL tool layer."""

    if state.sql_draft is None:
        raise ValueError("SqlDraft is required before SQL execution.")
    if state.sql_validation is None or not state.sql_validation.is_valid:
        raise ValueError("SQL must be valid before execution.")
    if state.sql_validation.status is SqlValidationStatus.INVALID:
        raise ValueError("Invalid SQL cannot be executed.")

    state.sql_result = query_data(
        data_source,
        state.sql_draft.query,
        limit=limit,
        timeout_seconds=timeout_seconds,
    )
    return state

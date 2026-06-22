"""Profile-constrained SQL drafter tests."""

from __future__ import annotations

from nodes.planning_nodes import interpret_question
from nodes.sql_nodes import draft_sql, validate_sql
from schemas.direct_analysis import DirectQuestionKind
from schemas.sql import SqlDialect, SqlDraft
from tests.phase49_sql_helpers import (
    CATEGORY_GMV_QUESTION,
    category_gmv_data_source,
    profiled_state,
)


def test_rule_topn_category_gmv_uses_profile_join_without_fake_fields() -> None:
    """Category GMV fallback should use real profile fields instead of invented orders fields."""

    data_source = category_gmv_data_source()
    state = profiled_state(data_source, CATEGORY_GMV_QUESTION)

    interpret_question(state)
    draft_sql(state, data_source=data_source)
    validate_sql(state, data_source=data_source)

    assert state.question_interpretation is not None
    assert state.question_interpretation.kind is DirectQuestionKind.TOP_N
    assert state.sql_draft is not None
    assert "JOIN products" in state.sql_draft.query
    assert "orders.category" not in state.sql_draft.query
    assert "orders.gmv" not in state.sql_draft.query
    assert "order_items.quantity * products.unit_price" in state.sql_draft.query
    assert state.sql_draft.used_fields == [
        "order_items.quantity",
        "products.unit_price",
        "products.category",
    ]
    assert state.sql_validation is not None
    assert state.sql_validation.is_valid is True


def test_validate_sql_checks_llm_declared_used_fields() -> None:
    """LLM-declared used_fields must exist in the datasource schema."""

    data_source = category_gmv_data_source()
    state = profiled_state(data_source, CATEGORY_GMV_QUESTION)
    state.sql_draft = SqlDraft(
        query="SELECT category, SUM(gmv) AS total_gmv FROM orders GROUP BY category",
        dialect=SqlDialect.SQLITE,
        used_tables=["orders"],
        used_fields=["orders.category", "orders.gmv"],
        generation_strategy="llm",
    )

    validate_sql(state, data_source=data_source)

    assert state.sql_validation is not None
    assert state.sql_validation.is_valid is False
    assert any("orders" in error for error in state.sql_validation.errors)
    assert any("orders.category" in error for error in state.sql_validation.errors)

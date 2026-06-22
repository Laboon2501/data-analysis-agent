"""Rule tests for follow-up metric corrections."""

from __future__ import annotations

from nodes.planning_nodes import interpret_question
from nodes.sql_nodes import draft_sql, validate_sql
from schemas.direct_analysis import DirectQuestionKind, QuestionInterpretation
from tests.phase49_sql_helpers import category_gmv_data_source, profiled_state


def test_average_unit_price_correction_keeps_category_topn_context() -> None:
    """A metric-only correction should preserve the prior category comparison."""

    data_source = category_gmv_data_source()
    state = profiled_state(data_source, "不是的，我是问平均单价，不是总销售额")
    state.is_followup_correction = True
    state.last_user_question = "这次销售额最高的品类是什么"
    state.last_question_interpretation = QuestionInterpretation(
        question="这次销售额最高的品类是什么",
        kind=DirectQuestionKind.TOP_N,
        table_name="order_items",
        metric_field="order_items.quantity",
        metric_aggregation="sum",
        dimension_field="products.category",
        top_n=1,
    )

    interpret_question(state)
    draft_sql(state, data_source=data_source)
    validate_sql(state, data_source=data_source)

    assert state.question_interpretation is not None
    assert state.question_interpretation.kind is DirectQuestionKind.TOP_N
    assert state.question_interpretation.metric_aggregation == "avg"
    assert state.question_interpretation.dimension_field.endswith(".category")
    assert state.question_interpretation.top_n == 1
    assert state.sql_draft is not None
    assert "AVG(" in state.sql_draft.query
    assert "GROUP BY" in state.sql_draft.query
    assert "ORDER BY AVG(" in state.sql_draft.query
    assert "LIMIT 1" in state.sql_draft.query
    assert "orders.category" not in state.sql_draft.query
    assert "orders.gmv" not in state.sql_draft.query
    assert state.sql_validation is not None
    assert state.sql_validation.is_valid is True

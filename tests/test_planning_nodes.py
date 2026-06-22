"""Tests for rule-based direct-analysis planning nodes."""

from nodes.planning_nodes import interpret_question
from schemas import AgentState
from schemas.database_profile import (
    DatabaseProfile,
    FieldProfile,
    FieldSemanticType,
    TableProfile,
    TableRole,
)
from schemas.direct_analysis import DirectQuestionKind


def test_time_trend_interpretation_uses_database_profile_time_fields() -> None:
    """中文时间趋势问题应从 DatabaseProfile.time_fields 补齐时间字段。"""

    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message="近 12 个月销售趋势怎么样？",
        database_profile=DatabaseProfile(
            datasource_id="demo",
            schema_hash="hash",
            tables=[
                TableProfile(
                    name="order_items",
                    role=TableRole.FACT,
                    columns=[
                        FieldProfile(
                            name="quantity",
                            data_type="integer",
                            semantic_type=FieldSemanticType.MEASURE,
                        )
                    ],
                ),
                TableProfile(
                    name="orders",
                    role=TableRole.FACT,
                    columns=[
                        FieldProfile(
                            name="order_month",
                            data_type="text",
                            semantic_type=FieldSemanticType.DATETIME,
                        ),
                        FieldProfile(
                            name="order_date",
                            data_type="text",
                            semantic_type=FieldSemanticType.DATETIME,
                        ),
                        FieldProfile(
                            name="gmv",
                            data_type="real",
                            semantic_type=FieldSemanticType.CURRENCY,
                        ),
                    ],
                ),
                TableProfile(
                    name="users",
                    role=TableRole.DIMENSION,
                    columns=[
                        FieldProfile(
                            name="signup_month",
                            data_type="text",
                            semantic_type=FieldSemanticType.DATETIME,
                        )
                    ],
                ),
            ],
            time_fields=[
                "users.signup_month",
                "orders.order_date",
                "orders.order_month",
            ],
            candidate_metrics=[
                "order_items.quantity",
                "orders.gmv",
            ],
            metric_fields=[
                "order_items.quantity",
                "orders.gmv",
            ],
        ),
    )

    interpret_question(state)

    assert state.question_interpretation is not None
    assert state.question_interpretation.kind is DirectQuestionKind.TIME_TREND
    assert state.question_interpretation.table_name == "orders"
    assert state.question_interpretation.time_field == "orders.order_month"
    assert state.question_interpretation.metric_field == "orders.gmv"

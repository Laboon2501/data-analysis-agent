"""Tests for compact AgentContextSummary creation."""

from app.context_summary import compact_context_summary
from schemas import (
    AgentCommand,
    AgentIntent,
    AgentState,
    DatabaseProfile,
    FieldProfile,
    FieldSemanticType,
    ProfileStatus,
    TableProfile,
)


def _profile() -> DatabaseProfile:
    return DatabaseProfile(
        datasource_id="demo",
        schema_hash="hash-1",
        status=ProfileStatus.CONFIRMED,
        tables=[
            TableProfile(
                name="orders",
                columns=[
                    FieldProfile(
                        name="order_month",
                        data_type="text",
                        semantic_type=FieldSemanticType.DATETIME,
                    ),
                    FieldProfile(
                        name="gmv",
                        data_type="real",
                        semantic_type=FieldSemanticType.MEASURE,
                        is_metric_candidate=True,
                    ),
                ],
            )
        ],
        candidate_metrics=["orders.gmv"],
        candidate_dimensions=["orders.order_month"],
        time_fields=["orders.order_month"],
        metric_fields=["orders.gmv"],
        dimension_fields=["orders.order_month"],
    )


def test_compact_context_summary_keeps_schema_and_intent() -> None:
    """摘要应保留可交接 schema 上下文，不保存正文 payload。"""

    state = AgentState(
        session_id="ctx",
        job_id="job",
        user_message="帮我看看字段",
        command=AgentCommand.SCHEMA_QA,
        intent=AgentIntent.SCHEMA_QA,
        datasource_id="demo",
        database_profile=_profile(),
        profile_status=ProfileStatus.CONFIRMED,
    )

    summary = compact_context_summary(state)

    assert summary.current_datasource_id == "demo"
    assert summary.schema_hash == "hash-1"
    assert summary.last_user_intent == "schema_qa"
    assert summary.known_tables == ["orders"]
    assert "orders.gmv" in summary.known_fields
    assert "orders.gmv" in summary.candidate_metrics


def test_compact_context_summary_redacts_secrets() -> None:
    """摘要不能持久化 API key、token 等敏感片段。"""

    state = AgentState(
        session_id="ctx-secret",
        job_id="job",
        user_message="我的 api_key=test-secret-value-123456789 字段有哪些",
        command=AgentCommand.SCHEMA_QA,
        intent=AgentIntent.SCHEMA_QA,
        datasource_id="demo",
        database_profile=_profile(),
        profile_status=ProfileStatus.CONFIRMED,
    )

    dumped = compact_context_summary(state).model_dump_json()

    assert "test-secret" not in dumped
    assert "[secret]" in dumped

"""Schema QA graph tests."""

from graphs.schema_qa_graph import build_schema_qa_graph
from schemas import AgentCommand, AgentIntent, AgentState, EventType


def test_schema_qa_graph_returns_field_summary_without_sql(sqlite_data_source) -> None:
    """Schema QA should profile metadata and answer without generating analysis SQL."""

    graph = build_schema_qa_graph(data_source=sqlite_data_source)
    state = AgentState(
        session_id="schema-qa",
        job_id="schema-qa-job",
        user_message="有哪些字段",
        command=AgentCommand.SCHEMA_QA,
        intent=AgentIntent.SCHEMA_QA,
        datasource_id=sqlite_data_source.datasource_id,
    )

    result = AgentState.model_validate(graph.invoke(state))

    assert result.intent is AgentIntent.SCHEMA_QA
    assert result.schema_qa_result is not None
    assert result.sql_draft is None
    assert result.sql_result is None
    assert "orders" in result.final_response_text
    assert "revenue" in result.final_response_text
    event_node_names = {event.node_name for event in result.events}
    assert "answer_schema_question" in event_node_names
    assert "execute_sql" not in event_node_names
    assert EventType.TEXT_DELTA in {event.event_type for event in result.events}


def test_schema_qa_llm_uses_bounded_profile_summary(sqlite_data_source) -> None:
    """LLM schema QA may polish the answer but cannot reference unknown fields."""

    from llm.fake import FakeLLMClient

    client = FakeLLMClient(
        [
            '{"answer":"字段包括 orders.revenue 和 customers.region，可按时间或地区分析。",'
            '"referenced_fields":["orders.revenue","customers.region"]}'
        ]
    )
    graph = build_schema_qa_graph(
        data_source=sqlite_data_source,
        node_strategy="llm",
        llm_client=client,
    )
    result = AgentState.model_validate(
        graph.invoke(
            AgentState(
                session_id="schema-qa",
                job_id="schema-qa-llm-job",
                user_message="把字段告诉我",
                command=AgentCommand.SCHEMA_QA,
                intent=AgentIntent.SCHEMA_QA,
                datasource_id=sqlite_data_source.datasource_id,
            )
        )
    )

    assert result.schema_qa_result is not None
    assert "orders.revenue" in result.schema_qa_result.answer
    assert len(client.calls) == 1
    user_payload = client.calls[0][-1].content
    assert "schema_summary" in user_payload
    assert "api_key" not in user_payload.lower()

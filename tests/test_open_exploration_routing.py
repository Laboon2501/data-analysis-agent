"""API routing tests for open exploration requests."""

from fastapi.testclient import TestClient

from app.api import create_app
from app.llm_runtime import LLMRuntimeMode
from app.workers import InMemoryJobRunner


def test_fake_llm_router_open_exploration_runs_graph(sqlite_data_source) -> None:
    """Web/API session 启用 fake LLM router 后，探索请求应实际进入开放探索图。"""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    client = TestClient(create_app(job_runner=runner))
    session_id = "fake-router-open"

    response = client.post(
        f"/sessions/{session_id}/llm",
        json={"mode": LLMRuntimeMode.FAKE_LLM.value, "enabled_nodes": ["router"]},
    )
    assert response.status_code == 200

    job_response = client.post(
        f"/sessions/{session_id}/chat",
        json={"message": "帮我探索性地分析一下这张表的数据"},
    )

    assert job_response.status_code == 200
    payload = job_response.json()
    final_state = payload["final_state"]
    assert payload["intent"] == "open_exploration"
    assert final_state["router_decision"]["source"] == "llm"
    assert final_state["router_decision"]["intent"] == "open_exploration"
    assert final_state["exploration_plan"] is not None
    assert final_state["exploration_findings"]
    assert "字段" not in (final_state.get("schema_qa_result") or {}).get("answer", "")
    events = client.get(f"/jobs/{payload['job_id']}/events").json()
    assert "generate_analysis_map" in {event.get("node_name") for event in events}


def test_field_question_still_uses_schema_qa(sqlite_data_source) -> None:
    """字段问题不应被开放探索关键词误吸收。"""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    client = TestClient(create_app(job_runner=runner))
    response = client.post(
        "/sessions/schema-router/chat",
        json={"message": "把字段告诉我"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "schema_qa"
    assert payload["final_state"]["schema_qa_result"] is not None
    assert payload["final_state"]["sql_draft"] is None

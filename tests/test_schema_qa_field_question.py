"""End-to-end schema QA checks for field-list questions."""

from fastapi.testclient import TestClient

from app.api import create_app
from app.workers import InMemoryJobRunner


def test_table_field_question_returns_schema_summary(sqlite_data_source) -> None:
    """字段问答应返回字段摘要，不应落入 report/export 缺少分析结果路径。"""

    client = TestClient(create_app(job_runner=InMemoryJobRunner(data_source=sqlite_data_source)))

    response = client.post(
        "/sessions/schema-field/chat",
        json={"message": "帮我看看这个表格都有哪些字段"},
    )

    assert response.status_code == 200
    payload = response.json()
    final_state = payload["final_state"]
    assert payload["intent"] == "schema_qa"
    assert final_state["schema_qa_result"] is not None
    assert "orders" in final_state["final_response_text"]
    assert "revenue" in final_state["final_response_text"]
    assert "当前会话没有可用的分析结果" not in final_state["final_response_text"]
    assert final_state["sql_draft"] is None
    assert final_state["analysis_package"] is None

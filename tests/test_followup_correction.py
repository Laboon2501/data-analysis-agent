"""Session follow-up correction tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import create_app
from app.workers import InMemoryJobRunner
from tests.phase49_sql_helpers import category_gmv_data_source


def test_followup_average_unit_price_uses_previous_category_intent() -> None:
    """The API path should pass prior structured analysis context into the next job."""

    data_source = category_gmv_data_source()
    runner = InMemoryJobRunner(data_source=data_source)
    client = TestClient(create_app(job_runner=runner))

    first = client.post(
        "/sessions/followup/chat",
        json={
            "message": "这次销售额最高的品类是什么",
            "datasource_id": data_source.datasource_id,
        },
    ).json()
    assert first["status"] == "completed"

    second = client.post(
        "/sessions/followup/chat",
        json={"message": "不是的，我是问平均单价，不是总销售额"},
    ).json()

    final_state = second["final_state"]
    sql = final_state["sql_draft"]["query"]
    assert second["status"] == "completed"
    assert final_state["is_followup_correction"] is True
    assert final_state["last_question_interpretation"] is not None
    assert final_state["question_interpretation"]["metric_aggregation"] == "avg"
    assert final_state["question_interpretation"]["dimension_field"].endswith(".category")
    assert "AVG(" in sql
    assert "GROUP BY" in sql
    assert "LIMIT 1" in sql
    assert "orders.category" not in sql
    assert "orders.gmv" not in sql

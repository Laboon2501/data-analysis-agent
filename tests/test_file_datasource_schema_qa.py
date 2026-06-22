"""File datasource schema QA tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.workers import InMemoryJobRunner
from datasource import DataSourceRegistry


def test_file_datasource_schema_qa_returns_fields_without_analysis_sql(tmp_path: Path) -> None:
    """CSV-backed datasource should answer field questions from profile metadata."""

    client = _client_with_file_datasource(tmp_path)
    client.post("/sessions/file-schema/datasource", json={"datasource_id": "orders-file"})

    response = client.post(
        "/sessions/file-schema/chat",
        json={"message": "把字段告诉我"},
    )

    assert response.status_code == 200
    payload = response.json()
    final_state = payload["final_state"]
    assert payload["intent"] == "schema_qa"
    assert payload["status"] == "completed"
    assert final_state["schema_qa_result"]["tables"][0]["fields"]
    assert "order_month" in payload["final_response_text"]
    assert "gmv" in payload["final_response_text"]
    assert final_state["sql_draft"] is None
    assert final_state["sql_result"] is None
    events = client.get(f"/jobs/{payload['job_id']}/events").json()
    assert "execute_sql" not in {event.get("node_name") for event in events}
    assert "2026-01,100" not in str(events)


def test_file_datasource_schema_qa_can_auto_profile(tmp_path: Path) -> None:
    """Unprofiled file datasource should be profiled by the schema QA graph."""

    client = _client_with_file_datasource(tmp_path)
    client.post("/sessions/file-schema-auto/datasource", json={"datasource_id": "orders-file"})

    response = client.post(
        "/sessions/file-schema-auto/chat",
        json={"message": "这个文件有哪些字段？"},
    )

    assert response.status_code == 200
    final_state = response.json()["final_state"]
    assert final_state["database_profile"] is not None
    assert final_state["schema_qa_result"]["analysis_suggestions"]


def _client_with_file_datasource(tmp_path: Path) -> TestClient:
    """Create a client with one CSV datasource."""

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_month,gmv,category\n2026-01,100,A\n2026-02,210,B\n",
        encoding="utf-8",
    )
    config = AppConfig(
        upload_dir=str(tmp_path / "uploads"),
        allow_local_file_paths=True,
    )
    registry = DataSourceRegistry()
    registry.register_file_from_path(
        datasource_id="orders-file",
        name="Orders file",
        file_path=csv_path,
        upload_dir=config.upload_dir,
        source_type="path",
        table_name="orders",
    )
    runner = InMemoryJobRunner(app_config=config, datasource_registry=registry)
    return TestClient(create_app(job_runner=runner, app_config=config))

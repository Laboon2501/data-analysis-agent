"""File datasource profile and analysis path tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.workers import InMemoryJobRunner
from datasource import DataSourceRegistry


def test_file_datasource_profile_uses_context_manager(tmp_path: Path) -> None:
    """A registered file datasource should profile through the existing context graph."""

    client = _client_with_file_datasource(tmp_path)

    response = client.post("/datasources/orders-file/profile")

    assert response.status_code == 200
    payload = response.json()
    profile = payload["final_state"]["database_profile"]
    assert payload["status"] == "completed"
    assert profile["datasource_id"] == "orders-file"
    assert "orders.order_month" in profile["time_fields"]
    assert "orders.gmv" in profile["candidate_metrics"]


def test_file_datasource_direct_analysis_reuses_sql_graph(tmp_path: Path) -> None:
    """Direct analysis over a file datasource should still use guarded SQL execution."""

    client = _client_with_file_datasource(tmp_path)

    response = client.post(
        "/sessions/session-file/datasource",
        json={"datasource_id": "orders-file"},
    )
    chat_response = client.post(
        "/sessions/session-file/chat",
        json={"message": "Show monthly GMV trend"},
    )

    assert response.status_code == 200
    assert chat_response.status_code == 200
    payload = chat_response.json()
    final_state = payload["final_state"]
    assert payload["status"] == "completed"
    assert final_state["intent"] == "direct_analysis"
    assert final_state["sql_draft"]["query"] == (
        "SELECT order_month, SUM(gmv) AS total_gmv "
        "FROM orders GROUP BY order_month ORDER BY order_month"
    )
    assert final_state["sql_result"]["rows"] == [
        {"order_month": "2026-01", "total_gmv": 100.0},
        {"order_month": "2026-02", "total_gmv": 210.0},
    ]
    assert "2026-01,100" not in str(client.get("/jobs/" + payload["job_id"] + "/events").json())


def _client_with_file_datasource(tmp_path: Path) -> TestClient:
    """Create a client with one CSV-backed datasource registered."""

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

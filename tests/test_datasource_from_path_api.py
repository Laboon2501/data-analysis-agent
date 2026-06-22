"""Datasource from-path API tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.workers import InMemoryJobRunner
from datasource import DataSourceRegistry


def test_from_path_api_rejects_local_paths_by_default(tmp_path: Path) -> None:
    """Local path registration is disabled unless explicitly configured."""

    csv_path = _write_csv(tmp_path / "orders.csv")
    client = _client(tmp_path, allow_local_file_paths=False)

    response = client.post(
        "/datasources/from-path",
        json={"path": str(csv_path), "datasource_id": "orders-file"},
    )

    assert response.status_code == 403
    assert "DATA_ANALYSIS_AGENT_ALLOW_LOCAL_FILE_PATHS" in response.json()["detail"]


def test_from_path_api_registers_csv_when_enabled(tmp_path: Path) -> None:
    """Enabled local path mode should register safe file datasource metadata only."""

    csv_path = _write_csv(tmp_path / "orders.csv")
    client = _client(tmp_path, allow_local_file_paths=True)

    response = client.post(
        "/datasources/from-path",
        json={
            "path": str(csv_path),
            "datasource_id": "orders-file",
            "name": "Orders file",
            "table_name": "orders",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["datasource_id"] == "orders-file"
    assert payload["kind"] == "file_csv"
    assert payload["name"] == "Orders file"
    assert payload["original_filename"] == "orders.csv"
    assert payload["source_type"] == "path"
    assert payload["table_name"] == "orders"
    assert payload["row_count"] == 2
    assert payload["columns"] == ["order_month", "gmv", "category"]
    assert payload["db_path"] is None
    assert payload["url"] is None


def test_from_path_api_rejects_sensitive_file_even_when_enabled(tmp_path: Path) -> None:
    """Sensitive local files should not become datasources even in local path mode."""

    env_path = tmp_path / ".env"
    env_path.write_text("SECRET=value\n", encoding="utf-8")
    client = _client(tmp_path, allow_local_file_paths=True)

    response = client.post(
        "/datasources/from-path",
        json={"path": str(env_path), "datasource_id": "secrets"},
    )

    assert response.status_code == 400
    assert "Sensitive environment files" in response.json()["detail"]


def _client(tmp_path: Path, *, allow_local_file_paths: bool) -> TestClient:
    """Create a file-datasource-capable API test client."""

    config = AppConfig(
        upload_dir=str(tmp_path / "uploads"),
        allow_local_file_paths=allow_local_file_paths,
    )
    runner = InMemoryJobRunner(
        app_config=config,
        datasource_registry=DataSourceRegistry(),
    )
    return TestClient(create_app(job_runner=runner, app_config=config))


def _write_csv(path: Path) -> Path:
    """Write a small orders CSV fixture."""

    path.write_text(
        "order_month,gmv,category\n2026-01,100,A\n2026-02,210,B\n",
        encoding="utf-8",
    )
    return path

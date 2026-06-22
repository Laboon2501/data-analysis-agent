"""Datasource upload API tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.workers import InMemoryJobRunner
from datasource import DataSourceRegistry


def test_upload_api_registers_csv_datasource(tmp_path: Path) -> None:
    """Multipart upload should register a queryable file datasource."""

    client = _client(tmp_path)

    response = client.post(
        "/datasources/upload",
        data={
            "datasource_id": "uploaded-orders",
            "name": "Uploaded Orders",
            "table_name": "orders",
        },
        files={
            "file": (
                "orders.csv",
                b"order_month,gmv,category\n2026-01,100,A\n2026-02,210,B\n",
                "text/csv",
            )
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["datasource_id"] == "uploaded-orders"
    assert payload["kind"] == "file_csv"
    assert payload["source_type"] == "upload"
    assert payload["original_filename"] == "orders.csv"
    assert payload["row_count"] == 2
    assert payload["db_path"] is None
    assert payload["url"] is None
    assert "2026-01" not in str(payload)


def test_upload_api_rejects_unsupported_extension(tmp_path: Path) -> None:
    """Only CSV, xlsx and Parquet files should be accepted."""

    client = _client(tmp_path)

    response = client.post(
        "/datasources/upload",
        files={"file": ("orders.txt", b"not,a,datasource\n", "text/plain")},
    )

    assert response.status_code == 400
    assert "Unsupported file datasource type" in response.json()["detail"]


def test_upload_api_rejects_path_traversal_filename(tmp_path: Path) -> None:
    """Upload filenames must not contain path separators."""

    client = _client(tmp_path)

    response = client.post(
        "/datasources/upload",
        files={"file": ("../orders.csv", b"order_month,gmv\n2026-01,100\n", "text/csv")},
    )

    assert response.status_code == 400
    assert "path separators" in response.json()["detail"]


def test_upload_api_rejects_file_larger_than_limit(tmp_path: Path) -> None:
    """Upload size limits should fail before the datasource is registered."""

    config = AppConfig(upload_dir=str(tmp_path / "uploads"), max_upload_mb=1)
    runner = InMemoryJobRunner(
        app_config=config,
        datasource_registry=DataSourceRegistry(),
    )
    client = TestClient(create_app(job_runner=runner, app_config=config))

    response = client.post(
        "/datasources/upload",
        files={"file": ("orders.csv", b"a" * (1024 * 1024 + 2), "text/csv")},
    )

    assert response.status_code == 400
    assert "exceeds limit" in response.json()["detail"]


def _client(tmp_path: Path) -> TestClient:
    """Create an API test client with an isolated upload directory."""

    config = AppConfig(upload_dir=str(tmp_path / "uploads"))
    runner = InMemoryJobRunner(
        app_config=config,
        datasource_registry=DataSourceRegistry(),
    )
    return TestClient(create_app(job_runner=runner, app_config=config))

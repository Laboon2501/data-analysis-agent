"""Human-readable error tests for file datasource upload and parsing."""

from __future__ import annotations

import builtins
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.workers import InMemoryJobRunner
from datasource import DataSourceRegistry
from datasource.file_datasource import import_file_to_sqlite


def test_upload_api_rejects_empty_file(tmp_path: Path) -> None:
    """Empty files should fail with a clear message before datasource registration."""

    client = _client(tmp_path)

    response = client.post(
        "/datasources/upload",
        files={"file": ("orders.csv", b"", "text/csv")},
    )

    assert response.status_code == 400
    assert "empty or missing a header" in response.json()["detail"]


def test_upload_api_rejects_sensitive_env_like_filename(tmp_path: Path) -> None:
    """Environment-looking upload names should be blocked even with CSV suffixes."""

    client = _client(tmp_path)

    response = client.post(
        "/datasources/upload",
        files={"file": (".env.csv", b"key,value\nSECRET,1\n", "text/csv")},
    )

    assert response.status_code == 400
    assert "Sensitive environment files" in response.json()["detail"]


def test_upload_api_reports_parse_failure_for_invalid_excel(tmp_path: Path) -> None:
    """Corrupt xlsx input should return a bounded parse error."""

    client = _client(tmp_path)

    response = client.post(
        "/datasources/upload",
        files={
            "file": (
                "orders.xlsx",
                b"this is not an xlsx workbook",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )

    assert response.status_code == 400
    assert "Failed to parse file datasource" in response.json()["detail"]


def test_parquet_import_reports_missing_optional_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parquet should fail clearly when pyarrow is unavailable."""

    parquet_path = tmp_path / "orders.parquet"
    parquet_path.write_bytes(b"not a parquet file")
    original_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("pyarrow"):
            raise ImportError("no pyarrow")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="requires optional dependency pyarrow"):
        import_file_to_sqlite(
            source_path=parquet_path,
            datasource_id="orders-file",
            output_dir=tmp_path / "uploads",
        )


def _client(tmp_path: Path) -> TestClient:
    """Create an isolated API client for upload error tests."""

    config = AppConfig(upload_dir=str(tmp_path / "uploads"))
    runner = InMemoryJobRunner(
        app_config=config,
        datasource_registry=DataSourceRegistry(),
    )
    return TestClient(create_app(job_runner=runner, app_config=config))

"""Security boundary tests for local and uploaded file datasources."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.sessions import InMemorySessionStore
from app.workers import InMemoryJobRunner
from datasource import DataSourceRegistry
from datasource.file_datasource import validate_supported_file_path


def test_validate_supported_file_path_rejects_sensitive_env_like_names(
    tmp_path: Path,
) -> None:
    """Environment-like filenames must not be registered as datasources."""

    env_csv = tmp_path / ".env.csv"
    env_csv.write_text("SECRET,value\n1,2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Sensitive environment files"):
        validate_supported_file_path(env_csv)


def test_validate_supported_file_path_rejects_sensitive_directories(
    tmp_path: Path,
) -> None:
    """Credential and system-looking directories should be blocked."""

    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    csv_path = ssh_dir / "orders.csv"
    csv_path.write_text("order_month,gmv\n2026-01,100\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Sensitive system or credential paths"):
        validate_supported_file_path(csv_path)


def test_validate_supported_file_path_rejects_path_traversal() -> None:
    """Local path registration should reject traversal syntax before resolving."""

    with pytest.raises(ValueError, match="Path traversal"):
        validate_supported_file_path(Path("demo") / ".." / "ecommerce_orders_demo.csv")


def test_uploaded_file_metadata_does_not_expose_server_paths(tmp_path: Path) -> None:
    """Upload responses should expose basename-style metadata only."""

    client = _client(tmp_path)

    response = client.post(
        "/datasources/upload",
        data={"datasource_id": "uploaded-orders", "table_name": "orders"},
        files={
            "file": (
                "orders.csv",
                b"order_month,gmv\n2026-01,100\n",
                "text/csv",
            )
        },
    )

    assert response.status_code == 200
    payload_text = str(response.json())
    assert "orders.csv" in payload_text
    assert str(tmp_path) not in payload_text
    assert "uploads" not in payload_text
    assert "sqlite" not in payload_text


def test_file_datasource_content_stays_out_of_events_history_and_response(
    tmp_path: Path,
) -> None:
    """Raw uploaded file body should not be persisted in events, history, or final text."""

    client = _client(tmp_path)
    upload_response = client.post(
        "/datasources/upload",
        data={
            "datasource_id": "uploaded-orders",
            "name": "Uploaded Orders",
            "table_name": "orders",
        },
        files={
            "file": (
                "orders.csv",
                b"order_month,gmv,category\n2026-01,100,SecretCategory\n",
                "text/csv",
            )
        },
    )
    select_response = client.post(
        "/sessions/file-session/datasource",
        json={"datasource_id": "uploaded-orders"},
    )
    chat_response = client.post(
        "/sessions/file-session/chat",
        json={"message": "Show monthly GMV trend"},
    )

    assert upload_response.status_code == 200
    assert select_response.status_code == 200
    assert chat_response.status_code == 200
    payload = chat_response.json()
    events_text = str(client.get(f"/jobs/{payload['job_id']}/events").json())
    messages_text = str(client.get("/sessions/file-session/messages").json())
    final_response = payload["final_state"]["final_response_text"]

    for forbidden in ["order_month,gmv,category", "2026-01,100,SecretCategory"]:
        assert forbidden not in events_text
        assert forbidden not in messages_text
        assert forbidden not in final_response


def _client(tmp_path: Path) -> TestClient:
    """Create an isolated API client for file datasource security tests."""

    config = AppConfig(upload_dir=str(tmp_path / "uploads"))
    session_store = InMemorySessionStore()
    runner = InMemoryJobRunner(
        app_config=config,
        datasource_registry=DataSourceRegistry(),
    )
    return TestClient(
        create_app(
            job_runner=runner,
            app_config=config,
            session_store=session_store,
        )
    )

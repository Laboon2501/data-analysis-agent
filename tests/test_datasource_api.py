"""Datasource management API 测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.workers import InMemoryJobRunner
from datasource import DataSourceRegistry


def test_datasource_api_registers_lists_and_gets_sqlite(tmp_path: Path) -> None:
    """API 应支持注册、列表和详情查询。"""

    db_path = _create_sqlite_file(tmp_path / "store.sqlite")
    client = _client()

    create_response = client.post(
        "/datasources",
        json={
            "datasource_id": "store",
            "name": "Store",
            "kind": "sqlite",
            "db_path": str(db_path),
        },
    )
    list_response = client.get("/datasources")
    get_response = client.get("/datasources/store")

    assert create_response.status_code == 200
    assert Path(create_response.json()["db_path"]).resolve() == db_path.resolve()
    assert list_response.status_code == 200
    assert [record["datasource_id"] for record in list_response.json()] == ["store"]
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Store"


def test_datasource_api_masks_password_in_response() -> None:
    """API response 不应暴露 SQLAlchemy URL 密码。"""

    client = _client()

    response = client.post(
        "/datasources",
        json={
            "datasource_id": "warehouse",
            "name": "Warehouse",
            "kind": "sqlalchemy",
            "url": "postgresql://user:secret@example.com/db",
        },
    )

    assert response.status_code == 200
    assert "secret" not in (response.json()["url"] or "")


def test_datasource_profile_endpoint_creates_context_job(tmp_path: Path) -> None:
    """profile endpoint 应提交 Context Manager job。"""

    db_path = _create_sqlite_file(tmp_path / "store.sqlite")
    registry = DataSourceRegistry()
    registry.register(
        datasource_id="store",
        name="Store",
        kind="sqlite",
        db_path=str(db_path),
    )
    client = _client(registry)

    response = client.post("/datasources/store/profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "context_manager"
    assert payload["final_state"]["datasource_id"] == "store"
    assert payload["final_state"]["database_profile"]["datasource_id"] == "store"

    datasource = client.get("/datasources/store").json()
    assert datasource["schema_hash"] == payload["final_state"]["database_profile"]["schema_hash"]
    assert datasource["last_profiled_at"] is not None


def test_unknown_datasource_profile_returns_404() -> None:
    """未知 datasource profile 请求应返回 404。"""

    response = _client().post("/datasources/missing/profile")

    assert response.status_code == 404


def _client(registry: DataSourceRegistry | None = None) -> TestClient:
    """创建带 datasource registry 的测试 API client。"""

    runner = InMemoryJobRunner(datasource_registry=registry or DataSourceRegistry())
    return TestClient(create_app(job_runner=runner))


def _create_sqlite_file(path: Path) -> Path:
    """创建最小 SQLite 文件供 API 测试使用。"""

    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, revenue REAL)")
        connection.execute("INSERT INTO orders (id, revenue) VALUES (1, 10.0)")
    return path

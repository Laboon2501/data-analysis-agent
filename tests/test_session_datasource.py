"""Session datasource 选择和分析入口保护测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.workers import InMemoryJobRunner
from datasource import DataSourceRegistry


def test_session_datasource_can_be_set_and_used_for_chat(tmp_path: Path) -> None:
    """session 选择 datasource 后，后续 chat 应使用该 datasource。"""

    registry = DataSourceRegistry()
    db_path = _create_sqlite_file(tmp_path / "store.sqlite", revenue=25.0)
    registry.register(
        datasource_id="store",
        name="Store",
        kind="sqlite",
        db_path=str(db_path),
    )
    client = _client(registry)

    set_response = client.post(
        "/sessions/session-1/datasource",
        json={"datasource_id": "store"},
    )
    chat_response = client.post(
        "/sessions/session-1/chat",
        json={"message": "What is total revenue?"},
    )

    assert set_response.status_code == 200
    assert set_response.json()["datasource_id"] == "store"
    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["status"] == "completed"
    assert payload["intent"] == "direct_analysis"
    assert payload["final_state"]["datasource_id"] == "store"
    assert payload["final_state"]["sql_result"]["rows"][0]["total_revenue"] == 25.0


def test_session_datasource_get_auto_returns_unique_datasource(tmp_path: Path) -> None:
    """只有一个 datasource 时，session 查询可返回自动选择结果。"""

    registry = DataSourceRegistry()
    db_path = _create_sqlite_file(tmp_path / "store.sqlite")
    registry.register(
        datasource_id="store",
        name="Store",
        kind="sqlite",
        db_path=str(db_path),
    )
    client = _client(registry)

    response = client.get("/sessions/session-1/datasource")

    assert response.status_code == 200
    assert response.json()["datasource_id"] == "store"


def test_analysis_without_any_datasource_returns_clear_prompt() -> None:
    """没有 datasource 时，分析请求不应进入 SQL。"""

    client = _client(DataSourceRegistry())

    response = client.post(
        "/sessions/session-1/chat",
        json={"message": "What is total revenue?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "clarification"
    final_state = payload["final_state"]
    assert final_state["sql_draft"] is None
    assert final_state["sql_result"] is None
    assert "数据源" in final_state["final_response_text"]


def test_analysis_with_multiple_datasources_requires_session_choice(tmp_path: Path) -> None:
    """多个 datasource 且 session 未选择时，不应猜测执行 SQL。"""

    registry = DataSourceRegistry()
    registry.register(
        datasource_id="store-a",
        name="Store A",
        kind="sqlite",
        db_path=str(_create_sqlite_file(tmp_path / "a.sqlite")),
    )
    registry.register(
        datasource_id="store-b",
        name="Store B",
        kind="sqlite",
        db_path=str(_create_sqlite_file(tmp_path / "b.sqlite")),
    )
    client = _client(registry)

    response = client.post(
        "/sessions/session-1/chat",
        json={"message": "What is total revenue?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "clarification"
    assert payload["final_state"]["sql_result"] is None
    assert "选择" in payload["final_state"]["final_response_text"]


def test_greeting_without_datasource_still_returns_help() -> None:
    """无 datasource 时 hi/help 也不能触发 SQL。"""

    client = _client(DataSourceRegistry())

    response = client.post("/sessions/session-1/chat", json={"message": "hi"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "clarification"
    assert payload["final_state"]["sql_result"] is None
    assert "数据分析 Agent" in payload["final_state"]["final_response_text"]


def _client(registry: DataSourceRegistry) -> TestClient:
    """创建测试 API client。"""

    runner = InMemoryJobRunner(datasource_registry=registry)
    return TestClient(create_app(job_runner=runner))


def _create_sqlite_file(path: Path, *, revenue: float = 10.0) -> Path:
    """创建带 orders 表的最小 SQLite 文件。"""

    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, month TEXT, revenue REAL)")
        connection.execute(
            "INSERT INTO orders (id, month, revenue) VALUES (1, '2026-01', ?)",
            (revenue,),
        )
    return path

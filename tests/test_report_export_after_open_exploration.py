"""Regression tests for exporting artifacts after open exploration."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig
from app.workers import InMemoryJobRunner
from datasource import DataSourceRegistry


def test_report_confirm_after_file_open_exploration_generates_outline_and_exports(
    tmp_path: Path,
) -> None:
    """文件数据源开放探索完成后，report_confirm 应补齐大纲并导出报告。"""

    client = _client_with_file_datasource(tmp_path)
    open_job = _run_file_open_exploration(client)

    confirm_response = client.post(
        "/sessions/session-file/chat",
        json={
            "message": "已确认继续生成报告",
            "command": "report_confirm",
            "analysis_package": open_job["final_state"]["analysis_package"],
        },
    )

    assert confirm_response.status_code == 200
    confirm_job = confirm_response.json()
    assert confirm_job["status"] == "completed"
    final_state = confirm_job["final_state"]
    assert final_state["report_outline"] is not None
    assert final_state["report_result"]["artifact_ref"].startswith("artifact:")
    assert final_state["final_response_text"].startswith("报告 已生成：artifact:")

    events = client.get(f"/jobs/{confirm_job['job_id']}/events").json()
    node_names = [event.get("node_name") for event in events]
    assert "generate_outline" in node_names
    assert "export_file" in node_names
    assert all(event["event_type"] != "error" for event in events)


@pytest.mark.parametrize(
    ("command", "expected_format"),
    [
        ("excel_confirm", "excel"),
        ("ppt_confirm", "ppt"),
        ("dashboard_confirm", "dashboard"),
    ],
)
def test_file_open_exploration_package_supports_export_confirms(
    tmp_path: Path,
    command: str,
    expected_format: str,
) -> None:
    """文件数据源探索结果应支持 Excel、PPT 和 Dashboard fast-path 导出。"""

    client = _client_with_file_datasource(tmp_path)
    open_job = _run_file_open_exploration(client)

    confirm_response = client.post(
        "/sessions/session-file/chat",
        json={
            "message": f"confirm {command}",
            "command": command,
            "analysis_package": open_job["final_state"]["analysis_package"],
        },
    )

    assert confirm_response.status_code == 200
    confirm_job = confirm_response.json()
    assert confirm_job["status"] == "completed"
    final_state = confirm_job["final_state"]
    assert final_state["report_result"]["report_format"] == expected_format
    assert final_state["report_result"]["artifact_ref"].startswith("artifact:")
    assert "Node 'export_file'" not in (confirm_job.get("error_message") or "")


def _run_file_open_exploration(client: TestClient) -> dict[str, object]:
    """选择文件数据源并运行一次开放探索。"""

    datasource_response = client.post(
        "/sessions/session-file/datasource",
        json={"datasource_id": "orders-file"},
    )
    assert datasource_response.status_code == 200

    open_response = client.post(
        "/sessions/session-file/chat",
        json={"message": "帮我看看这张表都有什么可以分析的", "command": "explore"},
    )
    assert open_response.status_code == 200
    open_job = open_response.json()
    assert open_job["status"] == "completed"
    assert open_job["final_state"]["intent"] == "open_exploration"
    assert open_job["final_state"]["analysis_package"] is not None
    assert "可导出" in open_job["final_state"]["final_response_text"]
    return open_job


def _client_with_file_datasource(tmp_path: Path) -> TestClient:
    """创建带 CSV 文件数据源的 API client。"""

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_month,gmv,category\n2026-01,100,A\n2026-02,210,B\n2026-03,160,A\n",
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

"""Tests for the FastAPI job and event skeleton."""

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.workers import InMemoryJobRunner
from schemas import ChartSpec, ChartType, Insight
from schemas.analysis_package import AnalysisPackage
from schemas.query_result import QueryColumn, QueryResult
from scripts.create_demo_db import create_demo_data_source


def _analysis_package() -> AnalysisPackage:
    """Create a package payload for report API requests."""

    return AnalysisPackage(
        question="What is total revenue?",
        sql_result=QueryResult(
            sql="SELECT SUM(revenue) AS total_revenue FROM orders",
            columns=[QueryColumn(name="total_revenue", data_type="real")],
            rows=[{"total_revenue": 310.0}],
            row_count=1,
        ),
        chart_spec=ChartSpec(chart_type=ChartType.TABLE, title="Total revenue"),
        insights=[
            Insight(
                title="Revenue summary",
                summary="\u6c47\u603b\u7ed3\u679c\u4e3a 310.0\u3002",
            )
        ],
    )


def _client(sqlite_data_source) -> TestClient:
    """Build a TestClient with an injected datasource-backed runner."""

    runner = InMemoryJobRunner(data_source=sqlite_data_source)
    return TestClient(create_app(job_runner=runner))


def test_chat_endpoint_creates_job_and_get_job_returns_status(sqlite_data_source) -> None:
    """POST chat should create a synchronous in-memory job that can be queried."""

    client = _client(sqlite_data_source)

    create_response = client.post(
        "/sessions/session-1/chat",
        json={"message": "What is total revenue?"},
    )
    assert create_response.status_code == 200
    created_job = create_response.json()
    assert created_job["status"] == "completed"
    assert created_job["intent"] == "direct_analysis"

    get_response = client.get(f"/jobs/{created_job['job_id']}")
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "completed"


def test_chat_endpoint_does_not_analyze_greeting(sqlite_data_source) -> None:
    """A greeting should return help text without SQL execution artifacts."""

    client = _client(sqlite_data_source)

    create_response = client.post(
        "/sessions/session-1/chat",
        json={"message": "hi"},
    )

    assert create_response.status_code == 200
    created_job = create_response.json()
    assert created_job["status"] == "completed"
    assert created_job["intent"] == "clarification"
    final_state = created_job["final_state"]
    assert final_state["sql_draft"] is None
    assert final_state["sql_result"] is None
    assert final_state["analysis_package"] is None
    assert "数据分析 Agent" in final_state["final_response_text"]

    events = client.get(f"/jobs/{created_job['job_id']}/events").json()
    assert "chart_ref" not in {event["event_type"] for event in events}


def test_chat_endpoint_handles_chinese_time_trend_with_profile_time_fields() -> None:
    """API direct analysis 应保留中文 message，并用 profile time_fields 生成趋势 SQL。"""

    data_source = create_demo_data_source()
    client = _client(data_source)
    message = "近 12 个月销售趋势怎么样？"

    create_response = client.post(
        "/sessions/session-cn/chat",
        json={"message": message},
    )

    assert create_response.status_code == 200
    created_job = create_response.json()
    assert created_job["status"] == "completed"
    final_state = created_job["final_state"]
    assert final_state["user_message"] == message
    assert final_state["database_profile"]["time_fields"] == [
        "orders.order_month",
        "orders.order_date",
        "users.signup_month",
    ]
    assert final_state["question_interpretation"]["time_field"] in {
        "orders.order_month",
        "orders.order_date",
    }
    assert final_state["sql_draft"]["query"].startswith("SELECT order_month")
    assert "FROM orders" in final_state["sql_draft"]["query"]

    events_response = client.get(f"/jobs/{created_job['job_id']}/events")
    assert events_response.status_code == 200
    assert all(event["event_type"] != "error" for event in events_response.json())


def test_events_endpoint_returns_recorded_events(sqlite_data_source) -> None:
    """GET job events should return stored event objects instead of opening SSE."""

    client = _client(sqlite_data_source)
    created_job = client.post(
        "/sessions/session-1/chat",
        json={"message": "What is total revenue?"},
    ).json()

    events_response = client.get(f"/jobs/{created_job['job_id']}/events")

    assert events_response.status_code == 200
    events = events_response.json()
    assert events
    assert {event["event_type"] for event in events}


def test_approve_endpoint_runs_report_confirm_fast_path(sqlite_data_source) -> None:
    """Approve should resume a waiting report job with the confirm command."""

    client = _client(sqlite_data_source)
    waiting_job = client.post(
        "/sessions/session-1/chat",
        json={
            "message": "export report",
            "command": "report",
            "analysis_package": _analysis_package().model_dump(mode="json"),
        },
    ).json()
    assert waiting_job["status"] == "waiting_for_human"

    approve_response = client.post(
        f"/jobs/{waiting_job['job_id']}/approve",
        json={"command": "report_confirm"},
    )

    assert approve_response.status_code == 200
    completed_job = approve_response.json()
    assert completed_job["status"] == "completed"
    assert completed_job["final_state"]["report_result"]["artifact_ref"].startswith("artifact:")


@pytest.mark.parametrize(
    "confirm_command",
    ["report_confirm", "excel_confirm", "ppt_confirm", "dashboard_confirm"],
)
def test_approve_endpoint_confirm_commands_skip_outline_regeneration(
    sqlite_data_source,
    confirm_command: str,
) -> None:
    """Confirm commands should reuse the saved outline and skip generate_outline."""

    client = _client(sqlite_data_source)
    waiting_job = client.post(
        "/sessions/session-1/chat",
        json={
            "message": "export report",
            "command": "report",
            "analysis_package": _analysis_package().model_dump(mode="json"),
        },
    ).json()
    assert waiting_job["status"] == "waiting_for_human"
    outline_id = waiting_job["final_state"]["report_outline"]["outline_id"]

    approve_response = client.post(
        f"/jobs/{waiting_job['job_id']}/approve",
        json={"command": confirm_command},
    )

    assert approve_response.status_code == 200
    completed_job = approve_response.json()
    assert completed_job["status"] == "completed"
    final_state = completed_job["final_state"]
    assert final_state["report_outline"]["outline_id"] == outline_id
    assert final_state["report_result"]["artifact_ref"].startswith("artifact:")

    events = client.get(f"/jobs/{waiting_job['job_id']}/events").json()
    event_types = [event["event_type"] for event in events]
    generate_outline_events = [
        event for event in events if event.get("node_name") == "generate_outline"
    ]
    assert len(generate_outline_events) == 2
    assert event_types.count("human_request") == 1
    assert event_types.count("done") == 1
    assert all(event["event_type"] != "error" for event in events)


def test_cancel_endpoint_sets_cancelled_status_and_event(sqlite_data_source) -> None:
    """Cancel should mark a waiting job cancelled and preserve events."""

    client = _client(sqlite_data_source)
    waiting_job = client.post(
        "/sessions/session-1/chat",
        json={
            "message": "export report",
            "command": "report",
            "analysis_package": _analysis_package().model_dump(mode="json"),
        },
    ).json()

    cancel_response = client.post(f"/jobs/{waiting_job['job_id']}/cancel")
    events_response = client.get(f"/jobs/{waiting_job['job_id']}/events")

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    assert any(event["event_type"] == "stopped" for event in events_response.json())

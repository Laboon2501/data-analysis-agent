"""Tests for chart artifact tools."""

from persistence import InMemoryArtifactStore
from schemas import ChartSpec, ChartType
from schemas.query_result import QueryColumn, QueryResult
from tools.chart_tools import CHART_MIME_TYPE, chart_ref_payload, generate_chart


def test_generate_chart_saves_lightweight_json_artifact() -> None:
    """Chart generation should persist JSON content and return only an artifact ref."""

    artifact_store = InMemoryArtifactStore()
    chart_spec = ChartSpec(
        chart_type=ChartType.LINE,
        title="Monthly revenue",
        x="month",
        y="total_revenue",
    )
    query_result = _query_result()

    artifact_ref = generate_chart(chart_spec, query_result, artifact_store=artifact_store)

    assert artifact_ref is not None
    record = artifact_store.get_artifact(artifact_ref)
    assert record is not None
    assert record.content["kind"] == "chart_artifact"
    assert record.content["mime_type"] == CHART_MIME_TYPE
    assert record.content["chart"]["chart_type"] == "line"
    assert record.content["data"]["rows"] == query_result.rows
    assert record.metadata["artifact_kind"] == "chart"
    assert record.metadata["mime_type"] == CHART_MIME_TYPE
    assert record.metadata["chart_id"] == chart_spec.chart_id


def test_generate_chart_returns_none_for_none_chart_type() -> None:
    """No chart artifact should be created for ChartType.NONE."""

    artifact_store = InMemoryArtifactStore()

    artifact_ref = generate_chart(
        ChartSpec(chart_type=ChartType.NONE),
        _query_result(),
        artifact_store=artifact_store,
    )

    assert artifact_ref is None


def test_chart_ref_payload_excludes_chart_content() -> None:
    """chart_ref event payload should include metadata but no rendered chart body."""

    metadata = {
        "mime_type": CHART_MIME_TYPE,
        "chart_type": "bar",
        "row_count": 3,
        "path": "artifact/path.json",
    }

    payload = chart_ref_payload("artifact:file:chart-1", metadata)

    assert payload == {
        "artifact_ref": "artifact:file:chart-1",
        "artifact_id": "chart-1",
        "path": "artifact/path.json",
        "mime_type": CHART_MIME_TYPE,
        "metadata": metadata,
    }
    assert "content" not in payload
    assert "chart_html" not in payload


def _query_result() -> QueryResult:
    """Build a small result set for chart tests."""

    return QueryResult(
        sql="SELECT month, SUM(revenue) AS total_revenue FROM orders GROUP BY month",
        columns=[
            QueryColumn(name="month", data_type="text"),
            QueryColumn(name="total_revenue", data_type="real"),
        ],
        rows=[
            {"month": "2026-01", "total_revenue": 100.0},
            {"month": "2026-02", "total_revenue": 210.0},
        ],
        row_count=2,
    )

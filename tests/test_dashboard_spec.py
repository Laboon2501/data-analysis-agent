"""Dashboard spec schema tests."""

from schemas import (
    ChartType,
    DashboardArtifactMetadata,
    DashboardFilter,
    DashboardLayout,
    DashboardSpec,
    DashboardWidget,
    DashboardWidgetType,
)


def test_dashboard_spec_carries_widgets_filters_and_artifact_refs() -> None:
    """DashboardSpec should reference chart artifacts without inline chart content."""

    widget = DashboardWidget(
        title="Revenue trend",
        widget_type=DashboardWidgetType.CHART,
        layout=DashboardLayout(x=0, y=0, w=6, h=4),
        chart_type=ChartType.LINE,
        chart_artifact_ref="artifact:chart-1",
        metadata={"chart_id": "chart-1"},
    )
    dashboard_filter = DashboardFilter(
        field="month",
        label="Month",
        values=["2026-01", "2026-02"],
    )

    spec = DashboardSpec(
        title="Revenue dashboard",
        source_package_id="package-1",
        question="Show monthly revenue trend",
        widgets=[widget],
        filters=[dashboard_filter],
    )

    payload = spec.model_dump(mode="json")
    assert payload["title"] == "Revenue dashboard"
    assert payload["widgets"][0]["chart_artifact_ref"] == "artifact:chart-1"
    assert payload["widgets"][0]["chart_type"] == "line"
    assert "chart_html" not in payload["widgets"][0]
    assert "rows" not in payload["widgets"][0]["metadata"]


def test_dashboard_artifact_metadata_is_lightweight() -> None:
    """Dashboard metadata should summarize the artifact without full spec content."""

    metadata = DashboardArtifactMetadata(
        dashboard_id="dashboard-1",
        title="Revenue dashboard",
        source_analysis_package_id="package-1",
        widget_count=3,
        filter_count=1,
        chart_artifact_refs=["artifact:chart-1"],
    )

    payload = metadata.model_dump(mode="json")
    assert payload["dashboard_id"] == "dashboard-1"
    assert payload["widget_count"] == 3
    assert payload["chart_artifact_refs"] == ["artifact:chart-1"]
    assert "widgets" not in payload

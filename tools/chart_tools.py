"""Chart artifact generation tools."""

from __future__ import annotations

from typing import Any

from persistence.interfaces import ArtifactStore
from schemas.chart import ChartSpec, ChartType
from schemas.query_result import QueryResult

CHART_MIME_TYPE = "application/vnd.data-analysis-agent.chart+json"


def generate_chart(
    chart_spec: ChartSpec,
    query_result: QueryResult,
    *,
    artifact_store: ArtifactStore,
) -> str | None:
    """Persist a lightweight chart JSON artifact and return only its reference."""

    if chart_spec.chart_type is ChartType.NONE:
        return None

    metadata = chart_artifact_metadata(chart_spec, query_result)
    artifact_content = {
        "kind": "chart_artifact",
        "mime_type": CHART_MIME_TYPE,
        "chart": chart_spec.model_copy(update={"artifact_ref": None}).model_dump(mode="json"),
        "data": {
            "result_id": query_result.result_id,
            "columns": [column.model_dump(mode="json") for column in query_result.columns],
            "rows": query_result.rows,
            "row_count": query_result.row_count,
            "truncated": query_result.truncated,
        },
    }
    return artifact_store.save_artifact(
        content=artifact_content,
        metadata=metadata,
    )


def chart_artifact_metadata(
    chart_spec: ChartSpec,
    query_result: QueryResult,
) -> dict[str, Any]:
    """Build small metadata used by artifact stores and chart_ref events."""

    return {
        "artifact_kind": "chart",
        "chart_id": chart_spec.chart_id,
        "chart_type": chart_spec.chart_type.value,
        "title": chart_spec.title,
        "mime_type": CHART_MIME_TYPE,
        "result_id": query_result.result_id,
        "row_count": query_result.row_count,
        "x": chart_spec.x,
        "y": chart_spec.y,
        "series": chart_spec.series,
    }


def chart_ref_payload(artifact_ref: str, metadata: dict[str, Any]) -> dict[str, Any]:
    """Build a stream-safe chart_ref event payload without artifact content."""

    return {
        "artifact_ref": artifact_ref,
        "artifact_id": _artifact_id_from_ref(artifact_ref),
        "path": metadata.get("path"),
        "mime_type": metadata.get("mime_type", CHART_MIME_TYPE),
        "metadata": dict(metadata),
    }


def _artifact_id_from_ref(artifact_ref: str) -> str:
    """Extract a stable id segment from an opaque artifact reference."""

    return artifact_ref.rsplit(":", maxsplit=1)[-1]


__all__ = [
    "CHART_MIME_TYPE",
    "chart_artifact_metadata",
    "chart_ref_payload",
    "generate_chart",
]

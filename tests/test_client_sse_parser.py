"""Tests for minimal API client SSE and artifact helpers."""

from __future__ import annotations

import pytest

from examples.client.minimal_client import (
    artifact_id_from_ref,
    extract_artifact_refs_from_payload,
    normalize_artifact_ref,
    parse_sse_frames,
)


def test_parse_sse_frames_decodes_event_and_json_data() -> None:
    """SSE parser should return event names and decoded JSON payloads."""

    text = (
        ": keepalive\r\n"
        "event: node_start\r\n"
        'data: {"event_type":"node_start","payload":{}}\r\n'
        "\r\n"
        "event: done\r\n"
        'data: {"event_type":"done"}\r\n'
        "\r\n"
    )

    frames = parse_sse_frames(text)

    assert frames == [
        {
            "event": "node_start",
            "data": {"event_type": "node_start", "payload": {}},
        },
        {
            "event": "done",
            "data": {"event_type": "done"},
        },
    ]


def test_parse_sse_frames_supports_multiline_data() -> None:
    """Multiple data lines should be joined before JSON decoding."""

    frames = parse_sse_frames('event: message\ndata: {"a":\ndata: 1}\n\n')

    assert frames == [{"event": "message", "data": {"a": 1}}]


def test_artifact_ref_helpers_normalize_raw_ids_and_namespaced_refs() -> None:
    """Client display refs should consistently use artifact:<id>."""

    assert artifact_id_from_ref("artifact:file:abc") == "abc"
    assert artifact_id_from_ref("raw-id") == "raw-id"
    assert normalize_artifact_ref("artifact:file:abc") == "artifact:abc"
    assert normalize_artifact_ref("raw-id") == "artifact:raw-id"

    with pytest.raises(ValueError, match="cannot be blank"):
        artifact_id_from_ref(" ")


def test_extract_artifact_refs_from_nested_payload() -> None:
    """Artifact refs should be collected from final state and event payload shapes."""

    payload = {
        "chart_spec": {"artifact_ref": "artifact:file:chart-1"},
        "report_result": {"artifact_id": "report-1"},
        "widgets": [
            {"chart_artifact_ref": "artifact:chart-1"},
            {"other": {"artifact_ref": "artifact:report-1"}},
        ],
    }

    assert extract_artifact_refs_from_payload(payload) == [
        "artifact:chart-1",
        "artifact:report-1",
    ]

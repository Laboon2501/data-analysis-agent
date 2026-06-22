"""Tests for extracting JSON objects from LLM output text."""

import pytest

from llm import LLMAdapterError, LLMErrorCode, extract_json_object


def test_extract_json_object_from_plain_json() -> None:
    """Plain JSON object output should parse directly."""

    assert extract_json_object('{"answer": 42}') == {"answer": 42}


def test_extract_json_object_from_fenced_model_output() -> None:
    """Model prose and markdown fences should be tolerated around the JSON object."""

    content = """
    Here is the result:

    ```json
    {"title": "Revenue", "nested": {"value": "{not a boundary}"}}
    ```
    """

    parsed = extract_json_object(content)

    assert parsed == {"title": "Revenue", "nested": {"value": "{not a boundary}"}}


@pytest.mark.parametrize(
    "content",
    [
        "no json here",
        '{"missing": true',
        "[1, 2, 3]",
        "{not valid json}",
    ],
)
def test_extract_json_object_rejects_invalid_outputs(content: str) -> None:
    """Invalid or non-object outputs should return structured JSON errors."""

    with pytest.raises(LLMAdapterError) as error_info:
        extract_json_object(content)

    assert error_info.value.detail.code is LLMErrorCode.JSON_INVALID

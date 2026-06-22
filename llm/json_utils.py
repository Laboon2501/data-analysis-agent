"""Utilities for extracting JSON objects from LLM text output."""

from __future__ import annotations

import json
from typing import Any

from llm.errors import LLMAdapterError, LLMErrorCode, LLMErrorDetail


def extract_json_object(content: str) -> dict[str, Any]:
    """Extract and validate the first JSON object embedded in model output."""

    json_text = _extract_first_object_text(content)
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise _invalid_json_error(content, "LLM output contained malformed JSON.") from exc
    if not isinstance(parsed, dict):
        raise _invalid_json_error(content, "LLM output JSON must be an object.")
    return parsed


def _extract_first_object_text(content: str) -> str:
    """Return the first balanced {...} substring while respecting string literals."""

    start_index = content.find("{")
    if start_index < 0:
        raise _invalid_json_error(content, "LLM output did not contain a JSON object.")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start_index, len(content)):
        character = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue

        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return content[start_index : index + 1]

    raise _invalid_json_error(content, "LLM output JSON object was not balanced.")


def _invalid_json_error(content: str, message: str) -> LLMAdapterError:
    """Build a structured JSON extraction error."""

    return LLMAdapterError(
        LLMErrorDetail(
            code=LLMErrorCode.JSON_INVALID,
            message=message,
            details={"content": content},
        )
    )

"""Small JSON serialization helpers for external persistence stores."""

from __future__ import annotations

import importlib
import json
from typing import Any

from pydantic import BaseModel

MODEL_MARKER = "pydantic_model"
PLAIN_MARKER = "plain"


def serialize_value(value: Any) -> str:
    """Serialize a cache/checkpoint value to a JSON string."""

    return json.dumps(_pack_value(value), ensure_ascii=False, default=str)


def deserialize_value(payload: str | bytes) -> Any:
    """Deserialize a value produced by serialize_value."""

    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    packed = json.loads(text)
    if not isinstance(packed, dict) or packed.get("kind") != MODEL_MARKER:
        return packed.get("value") if isinstance(packed, dict) and "value" in packed else packed

    module_name = packed["module"]
    class_name = packed["class"]
    model_payload = packed["value"]
    model_class = getattr(importlib.import_module(module_name), class_name)
    if not issubclass(model_class, BaseModel):
        raise TypeError(f"Serialized class is not a Pydantic model: {module_name}.{class_name}")
    return model_class.model_validate(model_payload)


def _pack_value(value: Any) -> dict[str, Any]:
    """Return a JSON-compatible envelope for one value."""

    if isinstance(value, BaseModel):
        return {
            "kind": MODEL_MARKER,
            "module": value.__class__.__module__,
            "class": value.__class__.__name__,
            "value": value.model_dump(mode="json"),
        }
    return {
        "kind": PLAIN_MARKER,
        "value": value,
    }

"""Small helpers for nodes that support rule/llm strategy switching."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from time import perf_counter
from typing import Any, Literal

from llm.base import LLMClient, LLMMessage, LLMResponse
from llm.errors import LLMAdapterError, LLMErrorCode, LLMErrorDetail
from llm.json_utils import extract_json_object
from llm.prompt_loader import PromptLoader
from schemas.agent_state import AgentState
from schemas.event import AgentEvent, EventType

NodeStrategy = Literal["rule", "llm"]
LLM_FALLBACK_EXCEPTIONS = (
    LLMAdapterError,
    TimeoutError,
    KeyError,
    TypeError,
    ValueError,
)
MAX_ERROR_SUMMARY_LENGTH = 300
SENSITIVE_VALUE_PATTERN = re.compile(r"sk-[A-Za-z0-9_-]+")
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)((?:api[_-]?key|authorization|bearer|token|secret)\s*[:=]\s*)[^\s,;'\"]+"
)


def call_llm_for_json(
    *,
    llm_client: LLMClient | None,
    prompt_name: str,
    user_payload: dict[str, Any],
    prompt_loader: PromptLoader | None = None,
    state: AgentState | None = None,
    node_name: str | None = None,
) -> dict[str, Any]:
    """Call a configured LLM and parse a single JSON object response."""

    active_node_name = node_name or prompt_name
    base_metadata = _base_llm_payload(
        node_name=active_node_name,
        prompt_name=prompt_name,
        llm_client=llm_client,
    )
    if llm_client is None:
        error = LLMAdapterError(
            LLMErrorDetail(
                code=LLMErrorCode.CLIENT_UNAVAILABLE,
                message="LLM strategy requires an llm_client.",
                details={"prompt_name": prompt_name},
            )
        )
        record_llm_error(
            state,
            node_name=active_node_name,
            exc=error,
            payload=base_metadata,
        )
        raise error

    active_prompt_loader = prompt_loader or PromptLoader()
    try:
        system_prompt = active_prompt_loader.load(prompt_name)
    except LLM_FALLBACK_EXCEPTIONS as exc:
        record_llm_error(
            state,
            node_name=active_node_name,
            exc=exc,
            payload=base_metadata,
        )
        raise

    messages = [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(
            role="user",
            content=json.dumps(user_payload, sort_keys=True, default=str),
        ),
    ]
    record_llm_start(
        state,
        node_name=active_node_name,
        payload={
            **base_metadata,
            "input_keys": sorted(user_payload),
        },
    )
    started_perf = perf_counter()
    try:
        response = llm_client.complete(
            messages,
            temperature=0,
        )
    except Exception as exc:
        duration_ms = _duration_ms(started_perf)
        record_llm_error(
            state,
            node_name=active_node_name,
            exc=exc,
            payload={**base_metadata, "duration_ms": duration_ms},
        )
        raise

    response_payload = {
        **base_metadata,
        **_response_metadata(response),
        "duration_ms": _duration_ms(started_perf),
    }
    record_llm_end(
        state,
        node_name=active_node_name,
        payload=response_payload,
    )
    try:
        return extract_json_object(response.content)
    except LLMAdapterError as exc:
        if exc.detail.code is LLMErrorCode.JSON_INVALID:
            record_llm_json_invalid(
                state,
                node_name=active_node_name,
                exc=exc,
                payload=response_payload,
            )
        else:
            record_llm_error(
                state,
                node_name=active_node_name,
                exc=exc,
                payload=response_payload,
            )
        raise


def parse_json_object(content: str) -> dict[str, Any]:
    """Parse an LLM response that should contain exactly one JSON object."""

    return extract_json_object(content)


def strategy_for_node(
    node_name: str,
    *,
    default_strategy: NodeStrategy = "rule",
    node_strategies: Mapping[str, NodeStrategy] | None = None,
) -> NodeStrategy:
    """Resolve the strategy for a single node from a per-node map."""

    if node_strategies is None:
        return default_strategy
    return node_strategies.get(node_name, default_strategy)


def record_llm_start(
    state: AgentState | None,
    *,
    node_name: str,
    payload: dict[str, object] | None = None,
) -> None:
    """Record the start of one LLM attempt without saving prompt content."""

    _append_llm_event(
        state,
        EventType.LLM_START,
        node_name=node_name,
        message=f"LLM node '{node_name}' started.",
        payload=payload,
    )


def record_llm_end(
    state: AgentState | None,
    *,
    node_name: str,
    payload: dict[str, object] | None = None,
) -> None:
    """Record successful provider completion without saving model output."""

    _append_llm_event(
        state,
        EventType.LLM_END,
        node_name=node_name,
        message=f"LLM node '{node_name}' completed.",
        payload=payload,
    )


def record_llm_error(
    state: AgentState | None,
    *,
    node_name: str,
    exc: Exception,
    payload: dict[str, object] | None = None,
) -> None:
    """Record a structured LLM error using redacted, bounded metadata."""

    _append_llm_event(
        state,
        EventType.LLM_ERROR,
        node_name=node_name,
        message=f"LLM node '{node_name}' failed.",
        payload={
            **(payload or {}),
            **_error_payload(exc),
        },
    )


def record_llm_json_invalid(
    state: AgentState | None,
    *,
    node_name: str,
    exc: Exception,
    payload: dict[str, object] | None = None,
) -> None:
    """Record invalid JSON output without saving the raw model response."""

    _append_llm_event(
        state,
        EventType.LLM_JSON_INVALID,
        node_name=node_name,
        message=f"LLM node '{node_name}' returned invalid JSON.",
        payload={
            **(payload or {}),
            **_error_payload(exc),
            "json_invalid": True,
        },
    )


def record_llm_fallback(
    state: AgentState,
    *,
    node_name: str,
    exc: Exception,
    llm_client: LLMClient | None = None,
    prompt_name: str | None = None,
) -> None:
    """Record a non-fatal LLM fallback event for graph observability."""

    payload = llm_fallback_payload(
        node_name=node_name,
        exc=exc,
        llm_client=llm_client,
        prompt_name=prompt_name,
    )
    state.events.append(
        AgentEvent(
            event_type=EventType.LLM_FALLBACK,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name=node_name,
            message=f"LLM node '{node_name}' fell back to rule strategy.",
            payload=payload,
        )
    )


def llm_fallback_payload(
    *,
    node_name: str,
    exc: Exception,
    llm_client: LLMClient | None = None,
    prompt_name: str | None = None,
) -> dict[str, object]:
    """Build a structured fallback payload from an exception."""

    payload: dict[str, object] = {
        **_base_llm_payload(
            node_name=node_name,
            prompt_name=prompt_name,
            llm_client=llm_client,
        ),
        "llm_fallback": True,
        "node": node_name,
        "fallback_reason": _error_summary(exc),
        "reason": _error_summary(exc),
        "switched_to_rule_strategy": True,
        **_error_payload(exc),
    }
    return payload


def _append_llm_event(
    state: AgentState | None,
    event_type: EventType,
    *,
    node_name: str,
    message: str,
    payload: dict[str, object] | None = None,
) -> None:
    """Append an LLM event when state is available."""

    if state is None:
        return
    state.events.append(
        AgentEvent(
            event_type=event_type,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name=node_name,
            message=message,
            payload=payload or {},
        )
    )


def _duration_ms(started_perf: float) -> float:
    return round((perf_counter() - started_perf) * 1000, 3)


def _base_llm_payload(
    *,
    node_name: str,
    prompt_name: str | None,
    llm_client: LLMClient | None,
) -> dict[str, object]:
    """Return safe metadata shared by LLM observability events."""

    payload: dict[str, object] = {"node_name": node_name}
    if prompt_name is not None:
        payload["prompt_name"] = prompt_name

    config = getattr(llm_client, "config", None)
    provider = getattr(config, "provider", None)
    model = getattr(config, "model", None)
    if provider is not None:
        payload["provider"] = str(provider)
    if model is not None:
        payload["model"] = str(model)
    return payload


def _response_metadata(response: LLMResponse) -> dict[str, object]:
    """Return bounded metadata from an LLMResponse without response content."""

    payload: dict[str, object] = {}
    if response.model is not None:
        payload["model"] = response.model
    provider = response.metadata.get("provider")
    if provider is not None:
        payload["provider"] = str(provider)
    finish_reason = response.metadata.get("finish_reason")
    if finish_reason is not None:
        payload["finish_reason"] = str(finish_reason)
    if response.usage:
        payload["usage"] = _safe_metadata(response.usage)
    return payload


def _error_payload(exc: Exception) -> dict[str, object]:
    """Return a redacted and bounded error payload."""

    payload: dict[str, object] = {
        "error_type": type(exc).__name__,
        "error_summary": _error_summary(exc),
    }
    if isinstance(exc, LLMAdapterError):
        payload["error_code"] = exc.detail.code.value
        payload["retryable"] = exc.detail.retryable
        payload["error_summary"] = _error_summary(exc.detail.message)
        safe_details = _safe_metadata(exc.detail.details)
        if safe_details:
            payload["metadata"] = safe_details
    return payload


def _safe_metadata(value: Any) -> object:
    """Copy only small, redacted diagnostic metadata into AgentState."""

    if isinstance(value, Mapping):
        safe: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                safe[key_text] = "<redacted>"
                continue
            if key_text in {"content", "response", "messages", "prompt"}:
                safe[f"{key_text}_length"] = len(str(item))
                continue
            safe[key_text] = _safe_metadata(item)
        return safe
    if isinstance(value, list | tuple):
        return [_safe_metadata(item) for item in value[:5]]
    if isinstance(value, str):
        return _truncate(_redact_sensitive_text(value))
    if isinstance(value, int | float | bool) or value is None:
        return value
    return _truncate(_redact_sensitive_text(str(value)))


def _is_sensitive_key(key: str) -> bool:
    """Return whether a metadata key might contain credentials."""

    normalized_key = key.lower().replace("-", "_")
    return any(token in normalized_key for token in ("api_key", "authorization", "token", "secret"))


def _error_summary(exc: Exception | str) -> str:
    """Return a redacted one-line error summary."""

    text = str(exc)
    return _truncate(_redact_sensitive_text(text.replace("\n", " ")))


def _redact_sensitive_text(text: str) -> str:
    """Redact common API key patterns from diagnostics."""

    redacted = SENSITIVE_VALUE_PATTERN.sub("sk-***", text)
    return SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1<redacted>", redacted)


def _truncate(text: str) -> str:
    """Bound diagnostic strings so events do not carry long raw output."""

    if len(text) <= MAX_ERROR_SUMMARY_LENGTH:
        return text
    return f"{text[:MAX_ERROR_SUMMARY_LENGTH]}..."

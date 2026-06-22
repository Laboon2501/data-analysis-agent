"""LLM runtime status, session rollout config, and deterministic fake client."""

from __future__ import annotations

import json
import os
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import Field

from app.config import AppConfig
from app.harness import LLMNodeStrategyConfig, build_node_strategy_map
from llm.base import LLMClient, LLMMessage, LLMResponse
from llm.config import ModelConfig
from llm.openai_compatible import OpenAICompatibleClient
from nodes.llm_strategy import NodeStrategy
from schemas._base import StrictBaseModel
from schemas.event import AgentEvent, EventType

ALLOWED_LLM_NODE_ALIASES: tuple[str, ...] = (
    "router",
    "planner",
    "sql_drafter",
    "insight_writer",
)
DEFAULT_REAL_LLM_PROVIDER = "openai_compatible"
DEFAULT_REAL_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_REAL_LLM_API_KEY_ENV = "OPENAI_API_KEY"


class LLMRuntimeMode(StrEnum):
    """LLM modes that can be selected through API or Web UI."""

    RULE = "rule"
    REAL_LLM = "real_llm"
    FAKE_LLM = "fake_llm"
    DISABLED = "disabled"


class SessionLLMConfig(StrictBaseModel):
    """Session-scoped LLM rollout config without API keys."""

    mode: LLMRuntimeMode = LLMRuntimeMode.RULE
    enabled_nodes: list[str] = Field(default_factory=list)


class LLMRuntimeStats(StrictBaseModel):
    """LLM observability counters for the latest job."""

    last_llm_call_count: int = 0
    last_llm_error_count: int = 0
    last_llm_fallback_count: int = 0
    last_llm_json_invalid_count: int = 0


class LLMRuntimeStatus(StrictBaseModel):
    """Frontend-safe LLM runtime status."""

    mode: LLMRuntimeMode = LLMRuntimeMode.RULE
    provider: str | None = None
    model: str | None = None
    base_url_host: str | None = None
    base_url_masked: str | None = None
    api_key_configured: bool = False
    enabled_nodes: list[str] = Field(default_factory=list)
    last_llm_call_count: int = 0
    last_llm_error_count: int = 0
    last_llm_fallback_count: int = 0
    last_llm_json_invalid_count: int = 0


class DeterministicFakeLLMClient(LLMClient):
    """Predictable fake LLM used by tests and local UI validation."""

    def __init__(self) -> None:
        self.calls: list[list[LLMMessage]] = []

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
    ) -> LLMResponse:
        """Record the call and return node-specific JSON."""

        _ = model, temperature, timeout_seconds
        self.calls.append([message.model_copy(deep=True) for message in messages])
        payload = _last_user_payload(messages)
        return LLMResponse(
            content=json.dumps(_fake_payload_for_node(payload), ensure_ascii=False),
            model="fake-llm",
            metadata={"provider": "fake_llm"},
        )


def normalize_session_llm_config(config: SessionLLMConfig) -> SessionLLMConfig:
    """Validate and dedupe a session LLM config."""

    return SessionLLMConfig(
        mode=config.mode,
        enabled_nodes=_normalize_enabled_nodes(config.enabled_nodes),
    )


def node_strategies_for_session(config: SessionLLMConfig) -> dict[str, NodeStrategy]:
    """Convert session LLM config to graph node strategy map."""

    normalized_config = normalize_session_llm_config(config)
    if normalized_config.mode not in {LLMRuntimeMode.REAL_LLM, LLMRuntimeMode.FAKE_LLM}:
        return {}
    return build_node_strategy_map(
        LLMNodeStrategyConfig(enabled_nodes=normalized_config.enabled_nodes)
    )


def build_llm_client_for_session(
    config: SessionLLMConfig,
    app_config: AppConfig,
) -> LLMClient | None:
    """Build the selected LLM client without changing rule-mode defaults."""

    normalized_config = normalize_session_llm_config(config)
    if normalized_config.mode in {LLMRuntimeMode.RULE, LLMRuntimeMode.DISABLED}:
        return None
    if normalized_config.mode is LLMRuntimeMode.FAKE_LLM:
        return DeterministicFakeLLMClient()
    model_config = model_config_from_app_config(app_config)
    _require_real_llm_ready(model_config)
    return OpenAICompatibleClient(model_config)


def model_config_from_app_config(app_config: AppConfig) -> ModelConfig:
    """Build real-provider model config from AppConfig."""

    return ModelConfig(
        provider=app_config.llm_provider or DEFAULT_REAL_LLM_PROVIDER,
        model=app_config.llm_model or "",
        base_url=app_config.llm_base_url or DEFAULT_REAL_LLM_BASE_URL,
        api_key_env=app_config.llm_api_key_env or DEFAULT_REAL_LLM_API_KEY_ENV,
        api_key=app_config.llm_api_key,
    )


def llm_status_from_config(
    *,
    app_config: AppConfig,
    session_config: SessionLLMConfig | None = None,
    stats: LLMRuntimeStats | None = None,
) -> LLMRuntimeStatus:
    """Build safe runtime status without returning API keys."""

    active_config = normalize_session_llm_config(
        session_config or SessionLLMConfig(enabled_nodes=app_config.llm_enabled_nodes)
    )
    model_config = model_config_from_app_config(app_config)
    active_stats = stats or LLMRuntimeStats()
    return LLMRuntimeStatus(
        mode=active_config.mode,
        provider=(
            model_config.provider
            if app_config.llm_provider or active_config.mode is not LLMRuntimeMode.RULE
            else None
        ),
        model=model_config.model or None,
        base_url_host=_base_url_host(model_config.base_url),
        base_url_masked=_base_url_masked(model_config.base_url),
        api_key_configured=_api_key_configured(model_config),
        enabled_nodes=active_config.enabled_nodes,
        **active_stats.model_dump(),
    )


def count_llm_events(events: list[AgentEvent]) -> LLMRuntimeStats:
    """Count LLM observability events from one job."""

    return LLMRuntimeStats(
        last_llm_call_count=sum(1 for event in events if event.event_type is EventType.LLM_START),
        last_llm_error_count=sum(1 for event in events if event.event_type is EventType.LLM_ERROR),
        last_llm_fallback_count=sum(
            1 for event in events if event.event_type is EventType.LLM_FALLBACK
        ),
        last_llm_json_invalid_count=sum(
            1 for event in events if event.event_type is EventType.LLM_JSON_INVALID
        ),
    )


def validate_real_llm_session_config(
    config: SessionLLMConfig,
    app_config: AppConfig,
) -> None:
    """Require model and API key before enabling real LLM for a session."""

    normalized_config = normalize_session_llm_config(config)
    if normalized_config.mode is not LLMRuntimeMode.REAL_LLM:
        return
    _require_real_llm_ready(model_config_from_app_config(app_config))


def _require_real_llm_ready(model_config: ModelConfig) -> None:
    """Validate real-provider model config without exposing secrets."""

    missing_fields = _missing_real_llm_fields(model_config)
    if missing_fields:
        detail = ", ".join(missing_fields)
        if "missing_api_key" in missing_fields and model_config.api_key_env:
            detail = f"{detail} (api_key_env={model_config.api_key_env})"
        raise ValueError(f"real_llm config is incomplete: {detail}.")


def _missing_real_llm_fields(model_config: ModelConfig) -> list[str]:
    """Return specific missing config fields for clear UI errors."""

    missing_fields: list[str] = []
    if not model_config.provider:
        missing_fields.append("missing_provider")
    if not model_config.model:
        missing_fields.append("missing_model")
    if not model_config.base_url:
        missing_fields.append("missing_base_url")
    if not _api_key_configured(model_config):
        missing_fields.append("missing_api_key")
    return missing_fields


def _normalize_enabled_nodes(enabled_nodes: list[str]) -> list[str]:
    """Validate and dedupe LLM node aliases in stable order."""

    seen: set[str] = set()
    normalized_nodes: list[str] = []
    for node_name in enabled_nodes:
        normalized = node_name.strip()
        if not normalized:
            continue
        if normalized not in ALLOWED_LLM_NODE_ALIASES:
            raise ValueError(f"Unsupported LLM node: {node_name}")
        if normalized not in seen:
            normalized_nodes.append(normalized)
            seen.add(normalized)
    return normalized_nodes


def _api_key_configured(model_config: ModelConfig) -> bool:
    """Return whether the API key is configured without exposing the raw value."""

    return bool(model_config.api_key or os.getenv(model_config.api_key_env))


def _base_url_host(base_url: str) -> str | None:
    """Return the host portion from a provider base URL."""

    parsed = urlparse(base_url)
    return parsed.netloc or parsed.path or None


def _base_url_masked(base_url: str) -> str:
    """Return a base URL without userinfo."""

    parsed = urlparse(base_url)
    if not parsed.netloc:
        return base_url
    host = parsed.hostname or parsed.netloc
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return parsed._replace(netloc=host).geturl()


def _last_user_payload(messages: list[LLMMessage]) -> dict[str, object]:
    """Parse the latest user message as JSON."""

    for message in reversed(messages):
        if message.role != "user":
            continue
        try:
            payload = json.loads(message.content)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _fake_payload_for_node(payload: dict[str, object]) -> dict[str, object]:
    """Return deterministic fake JSON for supported narrow tasks."""

    if payload.get("task") == "session_title":
        title = _compact_title(str(payload.get("user_message") or ""))
        return {"title": title, "summary": title}
    task = payload.get("task")
    if task == "router" or "current_intent" in payload:
        return _fake_router_payload(payload)
    if task == "chat_responder":
        return _fake_chat_payload(payload)
    if task == "schema_qa":
        return _fake_schema_qa_payload(payload)
    if task == "interpret_question":
        return _fake_interpretation_payload(payload)
    if task == "make_analysis_plan":
        return _fake_analysis_plan_payload()
    if "question_interpretation" in payload and "dialect" in payload:
        return _fake_sql_payload(payload)
    if "query_result" in payload:
        return {
            "title": "Fake LLM analysis insight",
            "summary": "Fake LLM reviewed the query result and produced a deterministic insight.",
            "evidence": ["fake_llm=true"],
            "confidence": 0.8,
        }
    return {}


def _fake_router_payload(payload: dict[str, object]) -> dict[str, object]:
    """Return deterministic intent routing JSON for fake LLM tests."""

    message = str(payload.get("user_message") or "").casefold()
    if any(token in message for token in ("ppt_confirm", "excel_confirm", "dashboard_confirm")):
        intent = "confirm_command"
    elif _fake_contains_any(message, ("hi", "hello", "你好", "help", "你能做什么")):
        intent = "help"
    elif _fake_contains_any(message, ("字段", "有哪些列", "columns", "fields")):
        intent = "schema_qa"
    elif _fake_contains_any(
        message,
        (
            "探索性",
            "探索分析",
            "有什么可以分析",
            "有什么发现",
            "自动分析",
            "explore",
            "exploration",
        ),
    ):
        intent = "open_exploration"
    elif _fake_contains_any(message, ("report", "ppt", "excel", "dashboard", "导出", "报告")):
        intent = "report_export"
    elif _fake_contains_any(
        message,
        ("trend", "top", "gmv", "销售", "趋势", "品类", "地区", "订单"),
    ):
        intent = "direct_analysis"
    else:
        intent = "chat"
    return {
        "intent": intent,
        "confidence": 0.92,
        "reason": f"FakeLLM 根据消息判定为 {intent}。",
        "needs_datasource": intent
        in {"schema_qa", "direct_analysis", "open_exploration", "report_export"},
        "is_followup": bool(payload.get("is_followup_correction")),
        "referenced_previous_context": bool(payload.get("last_user_question")),
    }


def _fake_contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    """Return whether any token is present for deterministic fake routing."""

    return any(token in text for token in tokens)


def _fake_chat_payload(payload: dict[str, object]) -> dict[str, object]:
    """Return deterministic fake no-tools chat JSON."""

    status = payload.get("llm_status")
    status_data = status if isinstance(status, dict) else {}
    mode = status_data.get("mode") or "fake_llm"
    provider = status_data.get("provider") or "fake_llm"
    model = status_data.get("model") or "fake-llm"
    answer = (
        f"当前是 {mode} 模式，模型配置为 {provider}/{model}。普通聊天不会执行 SQL，也不会调用工具。"
    )
    return {"answer": answer}


def _fake_schema_qa_payload(payload: dict[str, object]) -> dict[str, object]:
    """Return deterministic fake schema QA JSON from allowed fields."""

    allowed = payload.get("allowed_fields")
    allowed_fields = [str(field) for field in allowed] if isinstance(allowed, list) else []
    visible_fields = [field for field in allowed_fields if "." in field][:8]
    field_text = "、".join(visible_fields) if visible_fields else "暂无字段摘要"
    return {
        "answer": f"字段问答已基于数据源画像生成。可用字段包括：{field_text}。",
        "referenced_fields": visible_fields,
    }


def _fake_interpretation_payload(payload: dict[str, object]) -> dict[str, object]:
    """Return fake planner interpretation JSON."""

    question = str(payload.get("user_message") or "")
    profile = payload.get("database_profile")
    profile_data = profile if isinstance(profile, dict) else {}
    question_lower = question.casefold()
    is_trend = any(
        token in question_lower for token in ("trend", "month", "time", "时间", "趋势", "近", "月")
    )
    is_top = "top" in question_lower or "前" in question_lower or "排名" in question_lower
    time_field = (
        _pick_field(
            profile_data.get("time_fields") or [],
            preferred_tokens=("orders.order_month", "orders.order_date"),
            fallback="orders.order_month",
        )
        if is_trend
        else None
    )
    time_table, _ = _split_qualified(time_field) if time_field else (None, None)
    metric_field = _pick_metric_field(profile_data, preferred_table=time_table)
    table_name, _ = _split_qualified(metric_field)
    dimension_field = (
        _pick_field(
            profile_data.get("candidate_dimensions") or profile_data.get("dimension_fields") or [],
            preferred_tokens=(f"{table_name}.category", "category", "region"),
            fallback=f"{table_name}.category",
        )
        if is_top
        else None
    )
    return {
        "question": question,
        "kind": "time_trend" if is_trend else ("top_n" if is_top else "summary"),
        "table_name": table_name,
        "metric_field": metric_field,
        "time_field": time_field,
        "dimension_field": dimension_field,
        "top_n": 5 if is_top else None,
    }


def _fake_analysis_plan_payload() -> dict[str, object]:
    """Return fake make_analysis_plan JSON."""

    return {
        "steps": [
            {
                "name": "draft_sql",
                "objective": "Generate guarded SQL.",
                "required_inputs": ["database_profile", "question_interpretation"],
                "expected_outputs": ["sql_draft"],
                "tool_categories": ["sql"],
            }
        ],
        "assumptions": ["Fake LLM strategy for local testing."],
        "risks": [],
        "requires_human_confirmation": False,
    }


def _fake_sql_payload(payload: dict[str, object]) -> dict[str, object]:
    """Return deterministic SELECT SQL JSON for fake LLM tests."""

    interpretation = payload.get("question_interpretation")
    data = interpretation if isinstance(interpretation, dict) else {}
    table_name = str(data.get("table_name") or "orders")
    _, metric_column = _split_qualified(str(data.get("metric_field") or f"{table_name}.gmv"))
    kind = data.get("kind")
    if kind == "time_trend":
        _, time_column = _split_qualified(
            str(data.get("time_field") or f"{table_name}.order_month")
        )
        query = (
            f"SELECT {time_column}, SUM({metric_column}) AS total_{metric_column} "
            f"FROM {table_name} GROUP BY {time_column} ORDER BY {time_column}"
        )
    elif kind == "top_n":
        _, dimension_column = _split_qualified(
            str(data.get("dimension_field") or f"{table_name}.category")
        )
        top_n = int(data.get("top_n") or 5)
        query = (
            f"SELECT {dimension_column}, SUM({metric_column}) AS total_{metric_column} "
            f"FROM {table_name} GROUP BY {dimension_column} "
            f"ORDER BY SUM({metric_column}) DESC LIMIT {top_n}"
        )
    else:
        query = f"SELECT SUM({metric_column}) AS total_{metric_column} FROM {table_name}"
    return {"query": query, "rationale": "Fake LLM generated deterministic read-only SQL."}


def _pick_field(
    fields: object,
    *,
    preferred_tokens: tuple[str, ...],
    fallback: str,
) -> str:
    """Pick a field by token preference."""

    values = [str(field) for field in fields] if isinstance(fields, list) else []
    for token in preferred_tokens:
        for field in values:
            if token in field:
                return field
    return values[0] if values else fallback


def _pick_metric_field(
    profile_data: dict[str, object],
    *,
    preferred_table: str | None,
) -> str:
    """Pick a simple metric field that can be queried by fake LLM output."""

    fields = profile_data.get("candidate_metrics") or profile_data.get("metric_fields") or []
    values = [str(field) for field in fields] if isinstance(fields, list) else []
    preferred_tokens = ("gmv", "revenue", "sales_amount")
    if preferred_table is not None:
        same_table_fields = [
            field for field in values if _split_qualified(field)[0] == preferred_table
        ]
        for token in preferred_tokens:
            for field in same_table_fields:
                if token in field:
                    return field
        if same_table_fields:
            return same_table_fields[0]
    return _pick_field(
        values,
        preferred_tokens=preferred_tokens,
        fallback="orders.gmv",
    )


def _split_qualified(field: str) -> tuple[str, str]:
    """Split a table.column reference."""

    if "." not in field:
        return "orders", field
    table_name, column_name = field.split(".", maxsplit=1)
    return table_name, column_name


def _compact_title(value: str) -> str:
    clean = " ".join(str(value).split()).strip(" '\"`.,;:，。；：")
    if not clean:
        return "新对话"
    max_chars = 20 if any("\u4e00" <= char <= "\u9fff" for char in clean) else 40
    return clean[:max_chars]


__all__ = [
    "ALLOWED_LLM_NODE_ALIASES",
    "DEFAULT_REAL_LLM_API_KEY_ENV",
    "DEFAULT_REAL_LLM_BASE_URL",
    "DEFAULT_REAL_LLM_PROVIDER",
    "DeterministicFakeLLMClient",
    "LLMRuntimeMode",
    "LLMRuntimeStats",
    "LLMRuntimeStatus",
    "SessionLLMConfig",
    "build_llm_client_for_session",
    "count_llm_events",
    "llm_status_from_config",
    "model_config_from_app_config",
    "node_strategies_for_session",
    "normalize_session_llm_config",
    "validate_real_llm_session_config",
]

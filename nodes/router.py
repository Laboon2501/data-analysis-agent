"""Routing nodes for the direct analysis graph."""

from __future__ import annotations

from datasource.base import DataSource
from llm.base import LLMClient
from llm.prompt_loader import PromptLoader
from nodes.llm_strategy import (
    LLM_FALLBACK_EXCEPTIONS,
    NodeStrategy,
    call_llm_for_json,
    record_llm_fallback,
)
from persistence.interfaces import CacheStore
from schemas.agent_state import AgentCommand, AgentIntent, AgentState
from schemas.database_profile import ProfileStatus
from schemas.event import AgentEvent, EventType
from schemas.router import RouterDecision

ROUTER_CONFIDENCE_THRESHOLD = 0.55
LLM_INTENT_TO_ROUTE: dict[str, tuple[AgentCommand, AgentIntent]] = {
    "chat": (AgentCommand.NONE, AgentIntent.CLARIFICATION),
    "help": (AgentCommand.NONE, AgentIntent.CLARIFICATION),
    "unknown": (AgentCommand.NONE, AgentIntent.CLARIFICATION),
    "schema_qa": (AgentCommand.SCHEMA_QA, AgentIntent.SCHEMA_QA),
    "direct_analysis": (AgentCommand.ANALYZE, AgentIntent.DIRECT_ANALYSIS),
    "open_exploration": (AgentCommand.EXPLORE, AgentIntent.OPEN_EXPLORATION),
    "report_export": (AgentCommand.REPORT, AgentIntent.REPORT_EXPORT),
}


def route(
    state: AgentState,
    *,
    strategy: NodeStrategy = "rule",
    llm_client: LLMClient | None = None,
    prompt_loader: PromptLoader | None = None,
) -> AgentState:
    """Route the request with rule defaults and optional LLM strategy."""

    if strategy == "llm":
        try:
            return _route_with_llm(state, llm_client=llm_client, prompt_loader=prompt_loader)
        except LLM_FALLBACK_EXCEPTIONS as exc:
            record_llm_fallback(
                state,
                node_name="route",
                prompt_name="router",
                llm_client=llm_client,
                exc=exc,
            )
            return _route_with_rules(
                state,
                source="fallback",
                reason=f"LLM router fallback: {exc.__class__.__name__}",
            )
    return _route_with_rules(state)


def _route_with_rules(
    state: AgentState,
    *,
    source: str = "rule",
    reason: str = "Rule router defaulted to direct analysis.",
) -> AgentState:
    """Route the request into the direct analysis path."""

    from app.harness import infer_command_and_intent

    state.command, state.intent = infer_command_and_intent(state.user_message)
    _set_router_decision(
        state,
        RouterDecision(
            intent=state.intent.value,
            confidence=1.0 if source == "rule" else None,
            reason=reason,
            needs_datasource=_intent_needs_datasource(state.intent),
            is_followup=state.is_followup_correction,
            referenced_previous_context=bool(state.last_user_question),
            source="fallback" if source == "fallback" else "rule",
            command=state.command.value,
        ),
    )
    return state


def _route_with_llm(
    state: AgentState,
    *,
    llm_client: LLMClient | None,
    prompt_loader: PromptLoader | None,
) -> AgentState:
    """Route using a narrow JSON response from the router prompt."""

    payload = call_llm_for_json(
        llm_client=llm_client,
        prompt_name="router",
        prompt_loader=prompt_loader,
        state=state,
        node_name="route",
        user_payload={
            "task": "router",
            "user_message": state.user_message,
            "current_command": state.command.value,
            "current_intent": state.intent.value,
            "last_user_question": state.last_user_question,
            "agent_context_summary": (
                state.context_summary.model_dump(mode="json")
                if state.context_summary is not None
                else None
            ),
            "is_followup_correction": state.is_followup_correction,
        },
    )
    decision = _decision_from_llm_payload(payload, state)
    command, intent = _route_from_llm_intent(decision.intent)
    state.command = command
    state.intent = intent
    decision = decision.model_copy(update={"command": command.value, "intent": intent.value})
    _set_router_decision(state, decision)
    return state


def _decision_from_llm_payload(
    payload: dict[str, object],
    state: AgentState,
) -> RouterDecision:
    """Build a validated router decision from bounded LLM JSON."""

    raw_intent = str(payload.get("intent") or "").strip()
    if not raw_intent and payload.get("command"):
        raw_intent = _legacy_intent_from_command(str(payload.get("command")))
    confidence = payload.get("confidence")
    parsed_confidence = float(confidence) if confidence is not None else 1.0
    if parsed_confidence < ROUTER_CONFIDENCE_THRESHOLD:
        raise ValueError(f"Router confidence below threshold: {parsed_confidence}")
    command, intent = _route_from_llm_intent(raw_intent)
    return RouterDecision(
        intent=intent.value,
        confidence=parsed_confidence,
        reason=str(payload.get("reason") or "LLM router decision."),
        needs_datasource=bool(payload.get("needs_datasource", _intent_needs_datasource(intent))),
        is_followup=bool(payload.get("is_followup", state.is_followup_correction)),
        referenced_previous_context=bool(
            payload.get("referenced_previous_context", bool(state.last_user_question))
        ),
        source="llm",
        command=command.value,
    )


def _route_from_llm_intent(raw_intent: str) -> tuple[AgentCommand, AgentIntent]:
    """Map the narrow router intent label into workflow command/intent."""

    normalized = raw_intent.strip().lower()
    try:
        return LLM_INTENT_TO_ROUTE[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported router intent: {raw_intent}") from exc


def _legacy_intent_from_command(command: str) -> str:
    """Accept the previous router JSON shape used by older tests."""

    command_to_intent = {
        "none": "chat",
        "analyze": "direct_analysis",
        "explore": "open_exploration",
        "report": "report_export",
        "profile": "schema_qa",
        "schema_qa": "schema_qa",
    }
    return command_to_intent.get(command.strip().lower(), "")


def _intent_needs_datasource(intent: AgentIntent) -> bool:
    """Return whether an intent requires an active datasource before execution."""

    return intent in {
        AgentIntent.CONTEXT_MANAGER,
        AgentIntent.DIRECT_ANALYSIS,
        AgentIntent.OPEN_EXPLORATION,
        AgentIntent.REPORT_EXPORT,
        AgentIntent.SCHEMA_QA,
    }


def _set_router_decision(state: AgentState, decision: RouterDecision) -> None:
    """Persist router decision and emit a bounded observability event."""

    state.router_decision = decision
    state.events.append(
        AgentEvent(
            event_type=EventType.NODE_END,
            session_id=state.session_id,
            job_id=state.job_id,
            node_name="route",
            message=f"Router selected {decision.intent}.",
            payload={"router_decision": decision.model_dump(mode="json")},
        )
    )


def ensure_database_profile(
    state: AgentState,
    *,
    data_source: DataSource,
    cache_store: CacheStore | None = None,
) -> AgentState:
    """Ensure AgentState has a DatabaseProfile by invoking Context Manager when needed."""

    from graphs.context_manager_graph import build_context_manager_graph

    if state.database_profile is not None and state.profile_status not in {
        ProfileStatus.MISSING,
        ProfileStatus.FAILED,
    }:
        return state

    context_graph = build_context_manager_graph(
        data_source=data_source,
        cache_store=cache_store,
    )
    return AgentState.model_validate(context_graph.invoke(state))

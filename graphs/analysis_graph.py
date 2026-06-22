"""Direct analysis graph with a rule-based minimal closed loop."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial

from langgraph.graph import END, START, StateGraph

from datasource.base import DataSource
from guards.cancel_policy import CancelPolicy
from guards.retry_policy import RetryPolicy
from guards.timeout_policy import TimeoutPolicy
from llm.base import LLMClient
from llm.prompt_loader import PromptLoader
from nodes.chart_nodes import decide_chart, generate_chart_artifact
from nodes.execution_nodes import execute_sql
from nodes.final_nodes import build_analysis_package, final_response
from nodes.insight_nodes import generate_insight
from nodes.llm_strategy import NodeStrategy, strategy_for_node
from nodes.memory_nodes import retrieve_similar_cases
from nodes.planning_nodes import interpret_question, make_analysis_plan
from nodes.result_check_nodes import check_result, repair_sql_if_needed
from nodes.router import ensure_database_profile, route
from nodes.runtime import run_node_with_runtime
from nodes.sql_nodes import draft_sql, risk_check_sql, validate_sql
from persistence.interfaces import ArtifactStore, CacheStore, VectorMemoryStore
from persistence.memory_artifacts import InMemoryArtifactStore
from persistence.memory_cache import InMemoryCacheStore
from schemas.agent_state import AgentState

DIRECT_ANALYSIS_NODES: tuple[str, ...] = (
    "route",
    "ensure_database_profile",
    "retrieve_similar_cases",
    "interpret_question",
    "make_analysis_plan",
    "draft_sql",
    "validate_sql",
    "risk_check_sql",
    "execute_sql",
    "check_result",
    "repair_sql_if_needed",
    "decide_chart",
    "generate_chart_artifact",
    "generate_insight",
    "build_analysis_package",
    "final_response",
)


def build_analysis_graph(
    *,
    data_source: DataSource,
    cache_store: CacheStore | None = None,
    artifact_store: ArtifactStore | None = None,
    memory_store: VectorMemoryStore | None = None,
    retry_policy: RetryPolicy | None = None,
    timeout_policy: TimeoutPolicy | None = None,
    cancel_policy: CancelPolicy | None = None,
    node_strategy: NodeStrategy = "rule",
    node_strategies: Mapping[str, NodeStrategy] | None = None,
    llm_client: LLMClient | None = None,
    prompt_loader: PromptLoader | None = None,
):
    """Compile the direct analysis graph with injected datasource and stores."""

    active_cache_store = cache_store or InMemoryCacheStore()
    active_artifact_store = artifact_store or InMemoryArtifactStore()
    graph = StateGraph(AgentState)
    node_functions: dict[str, Callable[[AgentState], AgentState]] = {
        "route": partial(
            route,
            strategy=strategy_for_node(
                "route",
                default_strategy=node_strategy,
                node_strategies=node_strategies,
            ),
            llm_client=llm_client,
            prompt_loader=prompt_loader,
        ),
        "ensure_database_profile": partial(
            ensure_database_profile,
            data_source=data_source,
            cache_store=active_cache_store,
        ),
        "retrieve_similar_cases": partial(
            retrieve_similar_cases,
            memory_store=memory_store,
        ),
        "interpret_question": partial(
            interpret_question,
            strategy=strategy_for_node(
                "interpret_question",
                default_strategy=node_strategy,
                node_strategies=node_strategies,
            ),
            llm_client=llm_client,
            prompt_loader=prompt_loader,
        ),
        "make_analysis_plan": partial(
            make_analysis_plan,
            strategy=strategy_for_node(
                "make_analysis_plan",
                default_strategy=node_strategy,
                node_strategies=node_strategies,
            ),
            llm_client=llm_client,
            prompt_loader=prompt_loader,
        ),
        "draft_sql": partial(
            draft_sql,
            data_source=data_source,
            strategy=strategy_for_node(
                "draft_sql",
                default_strategy=node_strategy,
                node_strategies=node_strategies,
            ),
            llm_client=llm_client,
            prompt_loader=prompt_loader,
        ),
        "validate_sql": partial(validate_sql, data_source=data_source),
        "risk_check_sql": risk_check_sql,
        "execute_sql": partial(execute_sql, data_source=data_source),
        "check_result": check_result,
        "repair_sql_if_needed": partial(repair_sql_if_needed, data_source=data_source),
        "decide_chart": decide_chart,
        "generate_chart_artifact": partial(
            generate_chart_artifact,
            artifact_store=active_artifact_store,
        ),
        "generate_insight": partial(
            generate_insight,
            strategy=strategy_for_node(
                "generate_insight",
                default_strategy=node_strategy,
                node_strategies=node_strategies,
            ),
            llm_client=llm_client,
            prompt_loader=prompt_loader,
        ),
        "build_analysis_package": build_analysis_package,
        "final_response": final_response,
    }

    for node_name in DIRECT_ANALYSIS_NODES:
        graph.add_node(
            node_name,
            _runtime_wrapped_node(
                node_name=node_name,
                node_fn=node_functions[node_name],
                retry_policy=retry_policy,
                timeout_policy=timeout_policy,
                cancel_policy=cancel_policy,
            ),
        )

    graph.add_edge(START, "route")
    graph.add_edge("route", "ensure_database_profile")
    graph.add_edge("ensure_database_profile", "retrieve_similar_cases")
    graph.add_edge("retrieve_similar_cases", "interpret_question")
    graph.add_edge("interpret_question", "make_analysis_plan")
    graph.add_edge("make_analysis_plan", "draft_sql")
    graph.add_edge("draft_sql", "validate_sql")
    graph.add_conditional_edges(
        "validate_sql",
        route_after_validate_sql,
        {
            "risk_check_sql": "risk_check_sql",
            "repair_sql_if_needed": "repair_sql_if_needed",
        },
    )
    graph.add_conditional_edges(
        "repair_sql_if_needed",
        route_after_repair_sql,
        {
            "validate_sql": "validate_sql",
            "decide_chart": "decide_chart",
            "__end__": END,
        },
    )
    graph.add_edge("risk_check_sql", "execute_sql")
    graph.add_edge("execute_sql", "check_result")
    graph.add_edge("check_result", "repair_sql_if_needed")
    graph.add_edge("decide_chart", "generate_chart_artifact")
    graph.add_edge("generate_chart_artifact", "generate_insight")
    graph.add_edge("generate_insight", "build_analysis_package")
    graph.add_edge("build_analysis_package", "final_response")
    graph.add_edge("final_response", END)

    return graph.compile()


def route_after_validate_sql(state: AgentState) -> str:
    """Route only valid SQL toward execution; invalid SQL must be repaired first."""

    if state.sql_validation is not None and state.sql_validation.is_valid:
        return "risk_check_sql"
    return "repair_sql_if_needed"


def route_after_repair_sql(state: AgentState) -> str:
    """Continue after bounded SQL repair without executing invalid SQL."""

    if state.needs_human:
        return "__end__"
    if state.result_check is not None:
        return "decide_chart"
    if state.sql_validation is None and state.sql_draft is not None:
        return "validate_sql"
    if state.sql_validation is not None and state.sql_validation.is_valid:
        return "risk_check_sql"
    return "__end__"


def _runtime_wrapped_node(
    *,
    node_name: str,
    node_fn: Callable[[AgentState], AgentState],
    retry_policy: RetryPolicy | None,
    timeout_policy: TimeoutPolicy | None,
    cancel_policy: CancelPolicy | None,
):
    """Wrap a direct analysis node with shared runtime behavior."""

    def wrapped(state: AgentState) -> AgentState:
        return run_node_with_runtime(
            state=state,
            node_name=node_name,
            node_fn=node_fn,
            retry_policy=retry_policy,
            timeout_policy=timeout_policy,
            cancel_policy=cancel_policy,
        )

    wrapped.__name__ = node_name
    return wrapped

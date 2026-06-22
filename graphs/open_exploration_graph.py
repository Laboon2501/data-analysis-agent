"""Open exploration graph with rule-based topic generation and analysis."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from langgraph.graph import END, START, StateGraph

from datasource.base import DataSource
from guards.cancel_policy import CancelPolicy
from guards.retry_policy import RetryPolicy
from guards.timeout_policy import TimeoutPolicy
from nodes.exploration_nodes import (
    build_exploration_package,
    final_response,
    generate_analysis_map,
    optional_human_confirm,
    rank_topics,
    route,
    run_top_n_analyses,
    summarize_findings,
)
from nodes.router import ensure_database_profile
from nodes.runtime import run_node_with_runtime
from persistence.interfaces import CacheStore
from persistence.memory_cache import InMemoryCacheStore
from schemas.agent_state import AgentState

OPEN_EXPLORATION_NODES: tuple[str, ...] = (
    "route",
    "ensure_database_profile",
    "generate_analysis_map",
    "rank_topics",
    "optional_human_confirm",
    "run_top_n_analyses",
    "summarize_findings",
    "build_analysis_package",
    "final_response",
)


def build_open_exploration_graph(
    *,
    data_source: DataSource,
    cache_store: CacheStore | None = None,
    top_n: int = 3,
    require_human_confirmation: bool = False,
    retry_policy: RetryPolicy | None = None,
    timeout_policy: TimeoutPolicy | None = None,
    cancel_policy: CancelPolicy | None = None,
):
    """Compile the open exploration graph with injected datasource and cache."""

    active_cache_store = cache_store or InMemoryCacheStore()
    graph = StateGraph(AgentState)
    node_functions: dict[str, Callable[[AgentState], AgentState]] = {
        "route": route,
        "ensure_database_profile": partial(
            ensure_database_profile,
            data_source=data_source,
            cache_store=active_cache_store,
        ),
        "generate_analysis_map": partial(generate_analysis_map, top_n=top_n),
        "rank_topics": rank_topics,
        "optional_human_confirm": partial(
            optional_human_confirm,
            require_confirmation=require_human_confirmation,
        ),
        "run_top_n_analyses": partial(run_top_n_analyses, data_source=data_source),
        "summarize_findings": summarize_findings,
        "build_analysis_package": build_exploration_package,
        "final_response": final_response,
    }

    for node_name in OPEN_EXPLORATION_NODES:
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

    graph.add_edge(START, OPEN_EXPLORATION_NODES[0])
    for previous_node, next_node in zip(OPEN_EXPLORATION_NODES, OPEN_EXPLORATION_NODES[1:]):
        graph.add_edge(previous_node, next_node)
    graph.add_edge(OPEN_EXPLORATION_NODES[-1], END)

    return graph.compile()


def _runtime_wrapped_node(
    *,
    node_name: str,
    node_fn: Callable[[AgentState], AgentState],
    retry_policy: RetryPolicy | None,
    timeout_policy: TimeoutPolicy | None,
    cancel_policy: CancelPolicy | None,
):
    """Wrap an open exploration node with shared runtime behavior."""

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

"""Context Manager graph for rule-based database profiling."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from langgraph.graph import END, START, StateGraph

from datasource.base import DataSource
from guards.cancel_policy import CancelPolicy
from guards.retry_policy import RetryPolicy
from guards.timeout_policy import TimeoutPolicy
from nodes.context_nodes import (
    detect_ambiguity,
    generate_candidate_dimensions,
    generate_candidate_metrics,
    infer_field_semantics,
    infer_relationships,
    infer_table_roles,
    read_schema,
    sample_tables,
    save_profile_cache,
)
from nodes.runtime import run_node_with_runtime
from persistence.interfaces import CacheStore
from persistence.memory_cache import InMemoryCacheStore
from schemas.agent_state import AgentState

CONTEXT_MANAGER_NODES: tuple[str, ...] = (
    "read_schema",
    "sample_tables",
    "infer_table_roles",
    "infer_field_semantics",
    "infer_relationships",
    "generate_candidate_metrics",
    "generate_candidate_dimensions",
    "detect_ambiguity",
    "save_profile_cache",
)


def build_context_manager_graph(
    *,
    data_source: DataSource,
    cache_store: CacheStore | None = None,
    retry_policy: RetryPolicy | None = None,
    timeout_policy: TimeoutPolicy | None = None,
    cancel_policy: CancelPolicy | None = None,
):
    """Compile the Context Manager graph with injected datasource and cache."""

    active_cache_store = cache_store or InMemoryCacheStore()
    graph = StateGraph(AgentState)
    node_functions: dict[str, Callable[[AgentState], AgentState]] = {
        "read_schema": partial(
            read_schema,
            data_source=data_source,
            cache_store=active_cache_store,
        ),
        "sample_tables": partial(sample_tables, data_source=data_source),
        "infer_table_roles": infer_table_roles,
        "infer_field_semantics": infer_field_semantics,
        "infer_relationships": infer_relationships,
        "generate_candidate_metrics": generate_candidate_metrics,
        "generate_candidate_dimensions": generate_candidate_dimensions,
        "detect_ambiguity": detect_ambiguity,
        "save_profile_cache": partial(save_profile_cache, cache_store=active_cache_store),
    }

    for node_name in CONTEXT_MANAGER_NODES:
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

    graph.add_edge(START, CONTEXT_MANAGER_NODES[0])
    for previous_node, next_node in zip(CONTEXT_MANAGER_NODES, CONTEXT_MANAGER_NODES[1:]):
        graph.add_edge(previous_node, next_node)
    graph.add_edge(CONTEXT_MANAGER_NODES[-1], END)

    return graph.compile()


def _runtime_wrapped_node(
    *,
    node_name: str,
    node_fn: Callable[[AgentState], AgentState],
    retry_policy: RetryPolicy | None,
    timeout_policy: TimeoutPolicy | None,
    cancel_policy: CancelPolicy | None,
):
    """Wrap a context node with the shared node runtime."""

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

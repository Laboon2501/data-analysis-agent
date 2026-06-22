"""Report and export graph with confirmation fast-path support."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from langgraph.graph import END, START, StateGraph

from guards.cancel_policy import CancelPolicy
from guards.retry_policy import RetryPolicy
from guards.timeout_policy import TimeoutPolicy
from nodes.report_nodes import (
    analysis_package,
    export_file,
    generate_outline,
    request_report_confirm,
    return_artifact,
    route_after_analysis_package,
    should_export_after_confirmation,
)
from nodes.runtime import run_node_with_runtime
from persistence.interfaces import ArtifactStore
from persistence.memory_artifacts import InMemoryArtifactStore
from schemas.agent_state import AgentState
from schemas.report import ReportFormat

REPORT_EXPORT_NODES: tuple[str, ...] = (
    "analysis_package",
    "generate_outline",
    "human_confirm",
    "export_file",
    "return_artifact",
)


def build_report_graph(
    *,
    artifact_store: ArtifactStore | None = None,
    default_format: ReportFormat = ReportFormat.REPORT,
    retry_policy: RetryPolicy | None = None,
    timeout_policy: TimeoutPolicy | None = None,
    cancel_policy: CancelPolicy | None = None,
):
    """Compile the report graph for outline generation and confirmed exports."""

    active_artifact_store = artifact_store or InMemoryArtifactStore()
    graph = StateGraph(AgentState)
    node_functions: dict[str, Callable[[AgentState], AgentState]] = {
        "analysis_package": analysis_package,
        "generate_outline": partial(generate_outline, default_format=default_format),
        "human_confirm": request_report_confirm,
        "export_file": partial(export_file, artifact_store=active_artifact_store),
        "return_artifact": return_artifact,
    }

    for node_name in REPORT_EXPORT_NODES:
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

    graph.add_edge(START, "analysis_package")
    graph.add_conditional_edges(
        "analysis_package",
        route_after_analysis_package,
        {
            "generate_outline": "generate_outline",
            "export_file": "export_file",
        },
    )
    graph.add_edge("generate_outline", "human_confirm")
    graph.add_conditional_edges(
        "human_confirm",
        should_export_after_confirmation,
        {
            "export_file": "export_file",
            "__end__": END,
        },
    )
    graph.add_edge("export_file", "return_artifact")
    graph.add_edge("return_artifact", END)

    return graph.compile()


def _runtime_wrapped_node(
    *,
    node_name: str,
    node_fn: Callable[[AgentState], AgentState],
    retry_policy: RetryPolicy | None,
    timeout_policy: TimeoutPolicy | None,
    cancel_policy: CancelPolicy | None,
):
    """Wrap a report node with shared runtime behavior."""

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

"""Utilities for defining topology-only LangGraph skeletons."""

from __future__ import annotations

from collections.abc import Iterable

from langgraph.graph import END, START, StateGraph

from schemas.agent_state import AgentState


class SkeletonNodeNotImplementedError(NotImplementedError):
    """Raised when a skeleton graph node is invoked before its phase is implemented."""


def make_unimplemented_node(node_name: str):
    """Create a node placeholder that prevents fake business behavior."""

    def node(_: AgentState) -> AgentState:
        raise SkeletonNodeNotImplementedError(
            f"Node '{node_name}' is a Phase 1 skeleton and has no business logic yet."
        )

    node.__name__ = node_name
    return node


def build_linear_skeleton(node_names: Iterable[str]):
    """Build a linear LangGraph topology where every node is an explicit placeholder."""

    ordered_nodes = list(node_names)
    if not ordered_nodes:
        raise ValueError("A skeleton graph must contain at least one node.")

    graph = StateGraph(AgentState)
    for node_name in ordered_nodes:
        graph.add_node(node_name, make_unimplemented_node(node_name))

    graph.add_edge(START, ordered_nodes[0])
    for previous_node, next_node in zip(ordered_nodes, ordered_nodes[1:]):
        graph.add_edge(previous_node, next_node)
    graph.add_edge(ordered_nodes[-1], END)

    return graph.compile()

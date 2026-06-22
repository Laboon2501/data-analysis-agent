"""Tests for graph topology and remaining skeleton behavior."""

import pytest

from graphs import (
    CONTEXT_MANAGER_NODES,
    DIRECT_ANALYSIS_NODES,
    OPEN_EXPLORATION_NODES,
    REPORT_EXPORT_NODES,
    build_analysis_graph,
    build_context_manager_graph,
    build_open_exploration_graph,
    build_report_graph,
)
from nodes.runtime import NodeExecutionError
from schemas import AgentState

START_NODE = "__start__"
END_NODE = "__end__"


def _compiled_node_names(compiled_graph) -> set[str]:
    """Return public node names from a compiled LangGraph object."""

    return {
        node_name
        for node_name in compiled_graph.get_graph().nodes
        if not node_name.startswith("__")
    }


def _compiled_edges(compiled_graph) -> set[tuple[str, str]]:
    """Return graph edges as source and target name pairs."""

    return {(edge.source, edge.target) for edge in compiled_graph.get_graph().edges}


def _assert_linear_topology(compiled_graph, expected_nodes: tuple[str, ...]) -> None:
    """Assert that a graph preserves the declared linear node order."""

    expected_edges = (
        [(START_NODE, expected_nodes[0])]
        + list(zip(expected_nodes, expected_nodes[1:]))
        + [(expected_nodes[-1], END_NODE)]
    )

    assert _compiled_edges(compiled_graph) == set(expected_edges)
    assert all(edge.conditional is False for edge in compiled_graph.get_graph().edges)


def test_direct_analysis_graph_declares_required_phase_5_topology(sqlite_data_source) -> None:
    """The direct analysis graph should mirror the Phase 5 workflow order."""

    assert DIRECT_ANALYSIS_NODES == (
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

    compiled = build_analysis_graph(data_source=sqlite_data_source)
    edges = _compiled_edges(compiled)

    assert set(DIRECT_ANALYSIS_NODES).issubset(_compiled_node_names(compiled))
    assert {
        (START_NODE, "route"),
        ("route", "ensure_database_profile"),
        ("ensure_database_profile", "retrieve_similar_cases"),
        ("retrieve_similar_cases", "interpret_question"),
        ("interpret_question", "make_analysis_plan"),
        ("make_analysis_plan", "draft_sql"),
        ("draft_sql", "validate_sql"),
        ("validate_sql", "risk_check_sql"),
        ("validate_sql", "repair_sql_if_needed"),
        ("repair_sql_if_needed", "validate_sql"),
        ("repair_sql_if_needed", "decide_chart"),
        ("repair_sql_if_needed", END_NODE),
        ("risk_check_sql", "execute_sql"),
        ("execute_sql", "check_result"),
        ("check_result", "repair_sql_if_needed"),
        ("decide_chart", "generate_chart_artifact"),
        ("generate_chart_artifact", "generate_insight"),
        ("generate_insight", "build_analysis_package"),
        ("build_analysis_package", "final_response"),
        ("final_response", END_NODE),
    }.issubset(edges)
    assert any(
        edge.source == "validate_sql" and edge.conditional for edge in compiled.get_graph().edges
    )
    assert any(
        edge.source == "repair_sql_if_needed" and edge.conditional
        for edge in compiled.get_graph().edges
    )


def test_context_open_and_report_graphs_compile_with_declared_nodes(sqlite_data_source) -> None:
    """Real graphs should compile with declared nodes."""

    graph_specs = [
        (build_context_manager_graph(data_source=sqlite_data_source), CONTEXT_MANAGER_NODES),
        (build_open_exploration_graph(data_source=sqlite_data_source), OPEN_EXPLORATION_NODES),
        (build_report_graph(), REPORT_EXPORT_NODES),
    ]

    for compiled, expected_nodes in graph_specs:
        assert set(expected_nodes).issubset(_compiled_node_names(compiled))


def test_context_manager_graph_declares_linear_edge_order(sqlite_data_source) -> None:
    """Context Manager should preserve the declared linear profiling sequence."""

    _assert_linear_topology(
        build_context_manager_graph(data_source=sqlite_data_source),
        CONTEXT_MANAGER_NODES,
    )


def test_open_exploration_graph_declares_linear_edge_order(sqlite_data_source) -> None:
    """Open exploration should preserve the declared AGENTS.md graph sequence."""

    _assert_linear_topology(
        build_open_exploration_graph(data_source=sqlite_data_source),
        OPEN_EXPLORATION_NODES,
    )


def test_report_graph_declares_confirmation_branch() -> None:
    """Report export should stop for confirmation unless a fast-path command is active."""

    compiled = build_report_graph()
    edges = _compiled_edges(compiled)

    assert set(REPORT_EXPORT_NODES).issubset(_compiled_node_names(compiled))
    assert {
        (START_NODE, "analysis_package"),
        ("analysis_package", "generate_outline"),
        ("generate_outline", "human_confirm"),
        ("human_confirm", "export_file"),
        ("human_confirm", END_NODE),
        ("export_file", "return_artifact"),
        ("return_artifact", END_NODE),
    }.issubset(edges)
    assert any(
        edge.source == "human_confirm" and edge.conditional for edge in compiled.get_graph().edges
    )


def test_report_graph_missing_package_or_outline_fails_loudly() -> None:
    """Report graph must fail loudly instead of returning fake export results."""

    state = AgentState(session_id="session-1", job_id="job-1", user_message="sales by month")

    with pytest.raises(NodeExecutionError):
        build_report_graph().invoke(state)

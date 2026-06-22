"""Schema QA graph for controlled datasource field inspection."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from langgraph.graph import END, START, StateGraph

from datasource.base import DataSource
from guards.cancel_policy import CancelPolicy
from guards.retry_policy import RetryPolicy
from guards.timeout_policy import TimeoutPolicy
from llm.base import LLMClient
from llm.prompt_loader import PromptLoader
from nodes.llm_strategy import NodeStrategy
from nodes.router import ensure_database_profile
from nodes.runtime import run_node_with_runtime
from nodes.schema_qa_nodes import answer_schema_question
from persistence.interfaces import CacheStore
from persistence.memory_cache import InMemoryCacheStore
from schemas.agent_state import AgentState

SCHEMA_QA_NODES: tuple[str, ...] = (
    "ensure_database_profile",
    "answer_schema_question",
)


def build_schema_qa_graph(
    *,
    data_source: DataSource,
    cache_store: CacheStore | None = None,
    retry_policy: RetryPolicy | None = None,
    timeout_policy: TimeoutPolicy | None = None,
    cancel_policy: CancelPolicy | None = None,
    node_strategy: NodeStrategy = "rule",
    llm_client: LLMClient | None = None,
    prompt_loader: PromptLoader | None = None,
):
    """Compile the schema QA graph with datasource and optional LLM responder."""

    active_cache_store = cache_store or InMemoryCacheStore()
    graph = StateGraph(AgentState)
    node_functions: dict[str, Callable[[AgentState], AgentState]] = {
        "ensure_database_profile": partial(
            ensure_database_profile,
            data_source=data_source,
            cache_store=active_cache_store,
        ),
        "answer_schema_question": partial(
            answer_schema_question,
            strategy=node_strategy,
            llm_client=llm_client,
            prompt_loader=prompt_loader,
        ),
    }

    for node_name in SCHEMA_QA_NODES:
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

    graph.add_edge(START, "ensure_database_profile")
    graph.add_edge("ensure_database_profile", "answer_schema_question")
    graph.add_edge("answer_schema_question", END)
    return graph.compile()


def _runtime_wrapped_node(
    *,
    node_name: str,
    node_fn: Callable[[AgentState], AgentState],
    retry_policy: RetryPolicy | None,
    timeout_policy: TimeoutPolicy | None,
    cancel_policy: CancelPolicy | None,
):
    """Wrap a schema QA node with shared runtime behavior."""

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

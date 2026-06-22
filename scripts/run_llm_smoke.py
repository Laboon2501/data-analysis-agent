"""Manual local smoke test for OpenAI-compatible LLM strategy nodes."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.harness import LLMNodeStrategyConfig, build_node_strategy_map
from datasource import SQLAlchemyDataSource
from graphs.analysis_graph import build_analysis_graph
from llm.base import LLMClient, LLMMessage, LLMResponse
from llm.config import ModelConfig
from llm.openai_compatible import OpenAICompatibleClient
from schemas.agent_state import AgentState

DEFAULT_ENABLED_NODES = ("sql_drafter", "insight_writer")


class DebugLLMClient(LLMClient):
    """LLM client wrapper that records smoke-test call metadata."""

    def __init__(self, wrapped_client: LLMClient) -> None:
        self.wrapped_client = wrapped_client
        self.call_prompts: list[str] = []

    @property
    def call_count(self) -> int:
        """Return how many LLM calls were attempted."""

        return len(self.call_prompts)

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
    ) -> LLMResponse:
        """Record prompt metadata and delegate to the wrapped client."""

        self.call_prompts.append(_system_prompt_first_line(messages))
        return self.wrapped_client.complete(
            messages,
            model=model,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        )


@dataclass(frozen=True)
class SmokeDebugInfo:
    """Debug metadata emitted by the local smoke script."""

    requested_llm_nodes: list[str]
    enabled_llm_nodes: dict[str, str]
    llm_call_prompts: list[str]

    @property
    def llm_call_count(self) -> int:
        """Return how many LLM calls were recorded."""

        return len(self.llm_call_prompts)


@dataclass(frozen=True)
class SmokeRunResult:
    """Smoke run state plus debug metadata."""

    state: AgentState
    debug: SmokeDebugInfo


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse smoke-test CLI arguments without performing network calls."""

    parser = argparse.ArgumentParser(
        description="Run a manual direct-analysis smoke test against a real LLM provider."
    )
    parser.add_argument(
        "--provider",
        default="openai_compatible",
        help="LLM provider adapter name. Currently only openai_compatible is supported.",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Model name sent to the OpenAI-compatible provider.",
    )
    parser.add_argument(
        "--base-url",
        default="https://api.openai.com/v1",
        help="OpenAI-compatible API base URL.",
    )
    parser.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help="Environment variable that contains the provider API key.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30,
        help="Provider request timeout in seconds.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=1,
        help="Provider request retry count.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0,
        help="Provider temperature.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Optional provider max_tokens value.",
    )
    parser.add_argument(
        "--llm-node",
        action="append",
        choices=("router", "planner", "sql_drafter", "insight_writer"),
        dest="enabled_nodes",
        help=(
            "Node family to run with LLM strategy. Repeat the flag to enable more. "
            "Defaults to sql_drafter and insight_writer."
        ),
    )
    parser.add_argument(
        "--question",
        default="Show monthly revenue trend",
        help="Direct analysis question to run against the demo SQLite database.",
    )
    return parser.parse_args(argv)


def build_model_config(args: argparse.Namespace) -> ModelConfig:
    """Build ModelConfig from parsed CLI arguments."""

    return ModelConfig(
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )


def build_enabled_node_config(args: argparse.Namespace) -> LLMNodeStrategyConfig:
    """Return the LLM node rollout configuration from CLI args."""

    return LLMNodeStrategyConfig(enabled_nodes=requested_llm_nodes(args))


def requested_llm_nodes(args: argparse.Namespace) -> list[str]:
    """Return CLI-requested LLM nodes, applying smoke-test defaults."""

    return list(args.enabled_nodes or DEFAULT_ENABLED_NODES)


def create_demo_data_source() -> SQLAlchemyDataSource:
    """Create an in-memory SQLite datasource for local smoke tests."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY,
                    month TEXT NOT NULL,
                    region TEXT NOT NULL,
                    revenue REAL NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO orders (id, month, region, revenue)
                VALUES
                    (1, '2026-01', 'north', 100.0),
                    (2, '2026-02', 'north', 120.0),
                    (3, '2026-02', 'south', 90.0),
                    (4, '2026-03', 'south', 140.0)
                """
            )
        )
    return SQLAlchemyDataSource(
        datasource_id="llm-smoke-sqlite",
        engine=engine,
        dialect="sqlite",
    )


def run_smoke(args: argparse.Namespace) -> AgentState:
    """Run one direct analysis graph invocation with configured LLM nodes."""

    return run_smoke_with_debug(args).state


def run_smoke_with_debug(args: argparse.Namespace) -> SmokeRunResult:
    """Run one direct analysis graph invocation and collect debug metadata."""

    model_config = build_model_config(args)
    llm_client = DebugLLMClient(OpenAICompatibleClient(model_config))
    data_source = create_demo_data_source()
    llm_strategy_config = build_enabled_node_config(args)
    enabled_llm_nodes = build_node_strategy_map(llm_strategy_config)
    graph = build_analysis_graph(
        data_source=data_source,
        node_strategies=enabled_llm_nodes,
        llm_client=llm_client,
    )
    result = graph.invoke(
        AgentState(
            session_id="llm-smoke-session",
            job_id="llm-smoke-job",
            user_message=args.question,
            datasource_id=data_source.datasource_id,
        )
    )
    state = AgentState.model_validate(result)
    return SmokeRunResult(
        state=state,
        debug=SmokeDebugInfo(
            requested_llm_nodes=requested_llm_nodes(args),
            enabled_llm_nodes=enabled_llm_nodes,
            llm_call_prompts=list(llm_client.call_prompts),
        ),
    )


def build_state_summary(
    state: AgentState,
    debug: SmokeDebugInfo,
) -> dict[str, object]:
    """Build the JSON-serializable smoke output payload."""

    sql_result_payload = state.sql_result.model_dump(mode="json") if state.sql_result else None
    insight_payload = [insight.model_dump(mode="json") for insight in state.insights]
    errors_payload = [error.model_dump(mode="json") for error in state.errors]
    return {
        "final_response_text": state.final_response_text,
        "sql": state.sql_draft.query if state.sql_draft else None,
        "sql_result": sql_result_payload,
        "insights": insight_payload,
        "errors": errors_payload,
        "requested_llm_nodes": debug.requested_llm_nodes,
        "enabled_llm_nodes": debug.enabled_llm_nodes,
        "llm_call_count": debug.llm_call_count,
        "llm_call_prompts": debug.llm_call_prompts,
        "fallback_events": fallback_events_from_state(state),
    }


def fallback_events_from_state(state: AgentState) -> list[dict[str, object]]:
    """Extract LLM fallback events from AgentState."""

    return [
        dict(event.payload) for event in state.events if event.payload.get("llm_fallback") is True
    ]


def print_state_summary(state: AgentState, debug: SmokeDebugInfo) -> None:
    """Print a compact smoke-test result summary."""

    summary = build_state_summary(state, debug)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the manual smoke test from the command line."""

    args = parse_args(argv)
    result = run_smoke_with_debug(args)
    print_state_summary(result.state, result.debug)
    return 0


def _system_prompt_first_line(messages: list[LLMMessage]) -> str:
    """Return the first line of the system prompt for debug output."""

    system_message = next((message for message in messages if message.role == "system"), None)
    if system_message is None:
        return "<missing system prompt>"
    first_line = next(
        (line.strip() for line in system_message.content.splitlines() if line.strip()),
        "",
    )
    return first_line or "<empty system prompt>"


if __name__ == "__main__":
    raise SystemExit(main())

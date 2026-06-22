"""Offline eval runner for regression and optional real LLM checks."""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.config import AppConfig
from app.harness import LLMNodeStrategyConfig, build_initial_state, build_node_strategy_map
from datasource import SQLAlchemyDataSource
from datasource.file_datasource import import_file_to_sqlite
from evals.metrics import (
    EvalCase,
    EvalCaseResult,
    EvalSummary,
    evaluate_case_result,
    extract_sql_strings,
    summarize_eval_results,
)
from graphs.analysis_graph import build_analysis_graph
from graphs.context_manager_graph import build_context_manager_graph
from graphs.open_exploration_graph import build_open_exploration_graph
from graphs.report_graph import build_report_graph
from graphs.schema_qa_graph import build_schema_qa_graph
from llm.base import LLMClient
from llm.config import ModelConfig
from llm.fake import FakeLLMClient
from llm.openai_compatible import OpenAICompatibleClient
from nodes.llm_strategy import NodeStrategy
from persistence import InMemoryArtifactStore, InMemoryCacheStore
from schemas.agent_state import AgentCommand, AgentIntent, AgentState
from schemas.report import ReportFormat, ReportOutline, ReportOutlineSection
from scripts.create_demo_db import create_demo_data_source

EvalStrategy = Literal["rule", "fake-llm", "real-llm"]
DEFAULT_LLM_NODE_ALIASES: tuple[str, ...] = (
    "router",
    "planner",
    "sql_drafter",
    "insight_writer",
)

EVALS_DIR = Path(__file__).resolve().parent
DEFAULT_CASE_FILES: tuple[Path, ...] = (
    EVALS_DIR / "cases" / "direct_analysis_cases.jsonl",
    EVALS_DIR / "cases" / "open_exploration_cases.jsonl",
    EVALS_DIR / "cases" / "context_profile_cases.jsonl",
    EVALS_DIR / "cases" / "report_export_cases.jsonl",
    EVALS_DIR / "cases" / "schema_qa_cases.jsonl",
    EVALS_DIR / "cases" / "router_cases.jsonl",
    EVALS_DIR / "cases" / "demo_ecommerce_cases.jsonl",
)
LLM_EVAL_CASE_FILE = EVALS_DIR / "cases" / "llm_eval_cases.jsonl"
REPORT_COMMANDS: dict[ReportFormat, AgentCommand] = {
    ReportFormat.REPORT: AgentCommand.REPORT_CONFIRM,
    ReportFormat.PPT: AgentCommand.PPT_CONFIRM,
    ReportFormat.EXCEL: AgentCommand.EXCEL_CONFIRM,
    ReportFormat.DASHBOARD: AgentCommand.DASHBOARD_CONFIRM,
}


def load_eval_cases(case_file: Path | str) -> list[EvalCase]:
    """Load and validate eval cases from one JSONL file."""

    path = Path(case_file)
    cases: list[EvalCase] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            cases.append(EvalCase.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"Invalid eval case at {path}:{line_number}: {exc}") from exc
    return cases


def load_case_files(case_files: Iterable[Path | str] | None = None) -> list[EvalCase]:
    """Load one or more case files, defaulting to the offline regression suite."""

    active_files = tuple(Path(case_file) for case_file in (case_files or DEFAULT_CASE_FILES))
    cases: list[EvalCase] = []
    for case_file in active_files:
        cases.extend(load_eval_cases(case_file))
    return cases


def filter_cases_by_tags(cases: Iterable[EvalCase], tags: Iterable[str] | None) -> list[EvalCase]:
    """Return cases matching any requested tag; no tags means no filtering."""

    requested_tags = {tag for tag in tags or [] if tag}
    if not requested_tags:
        return list(cases)
    return [case for case in cases if requested_tags.intersection(case.tags)]


def run_eval_suite(
    *,
    case_files: Iterable[Path | str] | None = None,
    strategy: EvalStrategy = "rule",
    llm_nodes: Iterable[str] | None = None,
    output_path: Path | str | None = None,
    fake_llm_client: LLMClient | None = None,
    llm_client: LLMClient | None = None,
    model_config: ModelConfig | None = None,
    tags: Iterable[str] | None = None,
) -> EvalSummary:
    """Run the eval suite and optionally write summary JSON."""

    if strategy == "real-llm" and not tuple(llm_nodes or ()):
        raise RuntimeError("Real LLM eval requires explicit llm_nodes.")

    cases = filter_cases_by_tags(load_case_files(case_files), tags)
    results = [
        run_eval_case(
            eval_case,
            strategy=strategy,
            llm_nodes=llm_nodes,
            fake_llm_client=fake_llm_client,
            llm_client=llm_client,
            model_config=model_config,
        )
        for eval_case in cases
    ]
    summary = summarize_eval_results(results)
    if output_path is not None:
        Path(output_path).write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    return summary


def run_eval_case(
    case: EvalCase,
    *,
    strategy: EvalStrategy = "rule",
    llm_nodes: Iterable[str] | None = None,
    fake_llm_client: LLMClient | None = None,
    llm_client: LLMClient | None = None,
    model_config: ModelConfig | None = None,
) -> EvalCaseResult:
    """Run one case through the graph that matches its expected intent."""

    data_source = build_datasource_fixture(case.datasource_fixture)
    cache_store = InMemoryCacheStore()
    artifact_store = InMemoryArtifactStore()
    if "router-only" in case.tags:
        state = _run_router_case(
            case,
            strategy=strategy,
            llm_nodes=llm_nodes,
            fake_llm_client=fake_llm_client,
            llm_client=llm_client,
            model_config=model_config,
            data_source=data_source,
        )
        return evaluate_case_result(case, state)
    if case.expected_intent is AgentIntent.CONTEXT_MANAGER:
        state = _run_context_case(case, data_source=data_source, cache_store=cache_store)
        return evaluate_case_result(case, state)
    if case.expected_intent is AgentIntent.OPEN_EXPLORATION:
        state = _run_open_exploration_case(
            case,
            data_source=data_source,
            cache_store=cache_store,
        )
        return evaluate_case_result(case, state)
    if case.expected_intent is AgentIntent.REPORT_EXPORT:
        state, artifact_types, sql_strings = _run_report_export_case(
            case,
            data_source=data_source,
            cache_store=cache_store,
            artifact_store=artifact_store,
            strategy=strategy,
            llm_nodes=llm_nodes,
            fake_llm_client=fake_llm_client,
            llm_client=llm_client,
            model_config=model_config,
        )
        return evaluate_case_result(
            case,
            state,
            generated_artifact_types=artifact_types,
            sql_strings=sql_strings,
        )

    if case.expected_intent is AgentIntent.CLARIFICATION:
        state = _run_clarification_case(
            case,
            strategy=strategy,
            llm_nodes=llm_nodes,
            fake_llm_client=fake_llm_client,
            llm_client=llm_client,
            model_config=model_config,
            data_source=data_source,
        )
        return evaluate_case_result(case, state)
    if case.expected_intent is AgentIntent.SCHEMA_QA:
        state = _run_schema_qa_case(
            case,
            data_source=data_source,
            cache_store=cache_store,
            strategy=strategy,
            llm_nodes=llm_nodes,
            fake_llm_client=fake_llm_client,
            llm_client=llm_client,
            model_config=model_config,
        )
        return evaluate_case_result(case, state)

    state = _run_direct_analysis_case(
        case,
        data_source=data_source,
        cache_store=cache_store,
        artifact_store=artifact_store,
        strategy=strategy,
        llm_nodes=llm_nodes,
        fake_llm_client=fake_llm_client,
        llm_client=llm_client,
        model_config=model_config,
    )
    return evaluate_case_result(case, state)


def build_datasource_fixture(datasource_fixture: str) -> SQLAlchemyDataSource:
    """Build the SQLite datasource fixture used by offline evals."""

    if datasource_fixture == "sqlite_ecommerce_demo":
        return create_demo_data_source(datasource_id="eval-sqlite-ecommerce")
    if datasource_fixture == "file_ecommerce_orders_csv":
        return _build_file_ecommerce_orders_datasource()

    if datasource_fixture != "sqlite_orders":
        raise ValueError(f"Unknown datasource fixture: {datasource_fixture}")

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE customers (
                    id INTEGER PRIMARY KEY,
                    region TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY,
                    customer_id INTEGER NOT NULL,
                    month TEXT NOT NULL,
                    revenue REAL NOT NULL,
                    FOREIGN KEY(customer_id) REFERENCES customers(id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO customers (id, region)
                VALUES (1, 'north'), (2, 'south')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO orders (id, customer_id, month, revenue)
                VALUES
                    (1, 1, '2026-01', 100.0),
                    (2, 1, '2026-02', 120.0),
                    (3, 2, '2026-02', 90.0)
                """
            )
        )
    return SQLAlchemyDataSource(
        datasource_id="eval-sqlite-orders",
        engine=engine,
        dialect="sqlite",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse eval runner CLI arguments."""

    parser = argparse.ArgumentParser(description="Run offline Data Analysis Agent evals.")
    parser.add_argument(
        "--case-file",
        action="append",
        dest="case_files",
        help="JSONL case file to run. Can be provided multiple times.",
    )
    parser.add_argument(
        "--strategy",
        choices=("rule", "fake-llm", "real-llm"),
        default="rule",
        help="Node strategy for LLM-enabled direct-analysis nodes.",
    )
    parser.add_argument(
        "--llm-nodes",
        nargs="+",
        choices=DEFAULT_LLM_NODE_ALIASES,
        default=[],
        help=(
            "LLM node aliases to enable for --strategy real-llm. "
            "Supported: router planner sql_drafter insight_writer."
        ),
    )
    parser.add_argument("--llm-provider", help="Override LLM provider from AppConfig/env.")
    parser.add_argument("--llm-model", help="Override LLM model from AppConfig/env.")
    parser.add_argument("--llm-base-url", help="Override OpenAI-compatible base URL.")
    parser.add_argument("--llm-api-key-env", help="Override API key environment variable name.")
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Run only cases with this tag. Can be provided multiple times.",
    )
    parser.add_argument("--output", help="Optional path for summary JSON output.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for eval suite execution."""

    args = parse_args(argv)
    if args.strategy == "real-llm" and not args.llm_nodes:
        print(
            "--strategy real-llm requires --llm-nodes with at least one node alias.",
            file=sys.stderr,
        )
        return 2

    summary = run_eval_suite(
        case_files=args.case_files,
        strategy=args.strategy,
        llm_nodes=args.llm_nodes,
        output_path=args.output,
        fake_llm_client=FakeLLMClient() if args.strategy == "fake-llm" else None,
        tags=args.tag,
        model_config=(
            build_model_config_from_app_config(
                provider=args.llm_provider,
                model=args.llm_model,
                base_url=args.llm_base_url,
                api_key_env=args.llm_api_key_env,
            )
            if args.strategy == "real-llm"
            else None
        ),
    )
    print(summary.model_dump_json(indent=2))
    return 0 if summary.failed_cases == 0 else 1


def build_model_config_from_app_config(
    config: AppConfig | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
) -> ModelConfig:
    """Build real LLM eval config from explicit overrides or AppConfig/env."""

    active_config = config or AppConfig.from_env()
    active_provider = provider or active_config.llm_provider or "openai_compatible"
    active_model = model or active_config.llm_model
    if not active_model:
        raise RuntimeError(
            "Real LLM eval requires a model. Set DATA_ANALYSIS_AGENT_LLM_MODEL or pass --llm-model."
        )
    return ModelConfig(
        provider=active_provider,
        model=active_model,
        base_url=base_url or active_config.llm_base_url or "https://api.openai.com/v1",
        api_key_env=api_key_env or active_config.llm_api_key_env or "OPENAI_API_KEY",
    )


def build_real_llm_client(model_config: ModelConfig) -> LLMClient:
    """Build the configured real provider client for explicit real-llm eval runs."""

    if model_config.provider != "openai_compatible":
        raise ValueError(f"Unsupported LLM provider: {model_config.provider}")
    return OpenAICompatibleClient(model_config)


def _run_context_case(
    case: EvalCase,
    *,
    data_source: SQLAlchemyDataSource,
    cache_store: InMemoryCacheStore,
) -> AgentState:
    """Run the Context Manager graph."""

    state = AgentState(
        session_id="eval-session",
        job_id=_job_id(case),
        user_message=case.user_message,
        command=AgentCommand.PROFILE,
        intent=AgentIntent.CONTEXT_MANAGER,
        datasource_id=data_source.datasource_id,
    )
    return AgentState.model_validate(
        build_context_manager_graph(
            data_source=data_source,
            cache_store=cache_store,
        ).invoke(state)
    )


def _run_direct_analysis_case(
    case: EvalCase,
    *,
    data_source: SQLAlchemyDataSource,
    cache_store: InMemoryCacheStore,
    artifact_store: InMemoryArtifactStore,
    strategy: EvalStrategy,
    llm_nodes: Iterable[str] | None,
    fake_llm_client: LLMClient | None,
    llm_client: LLMClient | None,
    model_config: ModelConfig | None,
) -> AgentState:
    """Run the Direct Analysis graph."""

    node_strategy, node_strategies, active_llm_client = _node_strategy(
        strategy,
        llm_nodes=llm_nodes,
        fake_llm_client=fake_llm_client,
        llm_client=llm_client,
        model_config=model_config,
    )
    graph = build_analysis_graph(
        data_source=data_source,
        cache_store=cache_store,
        artifact_store=artifact_store,
        node_strategy=node_strategy,
        node_strategies=node_strategies,
        llm_client=active_llm_client,
    )
    prior_state: AgentState | None = None
    if case.previous_user_message:
        prior_state = _invoke_graph_safely(
            graph,
            AgentState(
                session_id="eval-session",
                job_id=f"{_job_id(case)}-previous",
                user_message=case.previous_user_message,
                datasource_id=data_source.datasource_id,
            ),
        )

    state = AgentState(
        session_id="eval-session",
        job_id=_job_id(case),
        user_message=case.user_message,
        datasource_id=data_source.datasource_id,
        last_user_question=prior_state.user_message if prior_state else None,
        last_question_interpretation=prior_state.question_interpretation if prior_state else None,
        last_analysis_plan=prior_state.analysis_plan if prior_state else None,
        last_sql_draft=prior_state.sql_draft if prior_state else None,
        last_sql_result_summary=_query_result_summary(prior_state),
        last_chart_spec=prior_state.chart_spec if prior_state else None,
        is_followup_correction=bool(prior_state),
    )
    return _invoke_graph_safely(graph, state)


def _run_clarification_case(
    case: EvalCase,
    *,
    strategy: EvalStrategy,
    llm_nodes: Iterable[str] | None,
    fake_llm_client: LLMClient | None,
    llm_client: LLMClient | None,
    model_config: ModelConfig | None,
    data_source: SQLAlchemyDataSource,
) -> AgentState:
    """Run only app-level routing for chat/help/invalid questions."""

    _, node_strategies, active_llm_client = _node_strategy(
        strategy,
        llm_nodes=llm_nodes,
        fake_llm_client=fake_llm_client,
        llm_client=llm_client,
        model_config=model_config,
    )
    route_strategy = "llm" if node_strategies and node_strategies.get("route") == "llm" else "rule"
    return build_initial_state(
        session_id="eval-session",
        job_id=_job_id(case),
        user_message=case.user_message,
        datasource_id=data_source.datasource_id,
        route_strategy=route_strategy,
        llm_strategy_config=(
            LLMNodeStrategyConfig(enabled_nodes=list(llm_nodes or ()))
            if route_strategy == "llm"
            else None
        ),
        llm_client=active_llm_client,
        model_config=model_config,
    )


def _run_router_case(
    case: EvalCase,
    *,
    strategy: EvalStrategy,
    llm_nodes: Iterable[str] | None,
    fake_llm_client: LLMClient | None,
    llm_client: LLMClient | None,
    model_config: ModelConfig | None,
    data_source: SQLAlchemyDataSource,
) -> AgentState:
    """Run app-level routing only for intent regression cases."""

    _, node_strategies, active_llm_client = _node_strategy(
        strategy,
        llm_nodes=llm_nodes,
        fake_llm_client=fake_llm_client,
        llm_client=llm_client,
        model_config=model_config,
    )
    route_strategy = "llm" if node_strategies and node_strategies.get("route") == "llm" else "rule"
    return build_initial_state(
        session_id="eval-session",
        job_id=_job_id(case),
        user_message=case.user_message,
        datasource_id=data_source.datasource_id,
        route_strategy=route_strategy,
        llm_strategy_config=(
            LLMNodeStrategyConfig(enabled_nodes=list(llm_nodes or ()))
            if route_strategy == "llm"
            else None
        ),
        llm_client=active_llm_client,
        model_config=model_config,
    )


def _run_schema_qa_case(
    case: EvalCase,
    *,
    data_source: SQLAlchemyDataSource,
    cache_store: InMemoryCacheStore,
    strategy: EvalStrategy,
    llm_nodes: Iterable[str] | None,
    fake_llm_client: LLMClient | None,
    llm_client: LLMClient | None,
    model_config: ModelConfig | None,
) -> AgentState:
    """Run the schema QA graph without generating analysis SQL."""

    node_strategy, _, active_llm_client = _node_strategy(
        strategy,
        llm_nodes=llm_nodes,
        fake_llm_client=fake_llm_client,
        llm_client=llm_client,
        model_config=model_config,
    )
    graph = build_schema_qa_graph(
        data_source=data_source,
        cache_store=cache_store,
        node_strategy=node_strategy,
        llm_client=active_llm_client,
    )
    return AgentState.model_validate(
        graph.invoke(
            AgentState(
                session_id="eval-session",
                job_id=_job_id(case),
                user_message=case.user_message,
                command=AgentCommand.SCHEMA_QA,
                intent=AgentIntent.SCHEMA_QA,
                datasource_id=data_source.datasource_id,
            )
        )
    )


def _run_open_exploration_case(
    case: EvalCase,
    *,
    data_source: SQLAlchemyDataSource,
    cache_store: InMemoryCacheStore,
) -> AgentState:
    """Run the Open Exploration graph."""

    graph = build_open_exploration_graph(
        data_source=data_source,
        cache_store=cache_store,
        top_n=3,
    )
    return AgentState.model_validate(
        graph.invoke(
            AgentState(
                session_id="eval-session",
                job_id=_job_id(case),
                user_message=case.user_message,
                datasource_id=data_source.datasource_id,
            )
        )
    )


def _run_report_export_case(
    case: EvalCase,
    *,
    data_source: SQLAlchemyDataSource,
    cache_store: InMemoryCacheStore,
    artifact_store: InMemoryArtifactStore,
    strategy: EvalStrategy,
    llm_nodes: Iterable[str] | None,
    fake_llm_client: LLMClient | None,
    llm_client: LLMClient | None,
    model_config: ModelConfig | None,
) -> tuple[AgentState, list[ReportFormat], list[str]]:
    """Build an AnalysisPackage, then run confirmed export fast-paths."""

    source_state = _run_direct_analysis_case(
        case,
        data_source=data_source,
        cache_store=cache_store,
        artifact_store=artifact_store,
        strategy=strategy,
        llm_nodes=llm_nodes,
        fake_llm_client=fake_llm_client,
        llm_client=llm_client,
        model_config=model_config,
    )
    if source_state.analysis_package is None:
        raise ValueError(f"Report eval case '{case.case_id}' did not build AnalysisPackage.")

    exported_types: list[ReportFormat] = []
    combined_events = list(source_state.events)
    final_state = source_state
    for report_format in case.expected_artifact_types or [ReportFormat.REPORT]:
        outline = _report_outline(report_format, source_state)
        report_state = AgentState(
            session_id="eval-session",
            job_id=_job_id(case),
            user_message=case.user_message,
            command=REPORT_COMMANDS[report_format],
            intent=AgentIntent.REPORT_EXPORT,
            datasource_id=data_source.datasource_id,
            analysis_package=source_state.analysis_package,
            report_outline=outline,
        )
        final_state = _invoke_graph_safely(
            build_report_graph(artifact_store=artifact_store),
            report_state,
        )
        combined_events.extend(final_state.events)
        if final_state.report_result is not None:
            exported_types.append(final_state.report_result.report_format)

    final_state.intent = AgentIntent.REPORT_EXPORT
    final_state.sql_draft = source_state.sql_draft
    final_state.sql_result = source_state.sql_result
    final_state.chart_spec = source_state.chart_spec
    final_state.events = combined_events
    return final_state, exported_types, extract_sql_strings(source_state)


def _report_outline(report_format: ReportFormat, source_state: AgentState) -> ReportOutline:
    """Build a confirmed lightweight outline without re-planning analysis."""

    package = source_state.analysis_package
    if package is None:
        raise ValueError("AnalysisPackage is required for report eval export.")
    return ReportOutline(
        report_format=report_format,
        title=f"Eval {report_format.value} export",
        sections=[
            ReportOutlineSection(
                title="Summary",
                points=[source_state.final_response_text or "Analysis completed."],
            )
        ],
        source_package_id=package.package_id,
    )


def _node_strategy(
    strategy: EvalStrategy,
    *,
    llm_nodes: Iterable[str] | None,
    fake_llm_client: LLMClient | None,
    llm_client: LLMClient | None,
    model_config: ModelConfig | None,
) -> tuple[NodeStrategy, dict[str, NodeStrategy] | None, LLMClient | None]:
    """Resolve eval strategy into graph strategy, per-node map, and LLM client."""

    if strategy == "rule":
        return "rule", None, None

    enabled_nodes = tuple(llm_nodes or ())
    if strategy == "fake-llm":
        active_client = fake_llm_client or llm_client or FakeLLMClient()
        if not enabled_nodes:
            return "llm", None, active_client
        return "rule", _node_strategy_map(enabled_nodes), active_client

    if not enabled_nodes:
        raise RuntimeError("Real LLM eval requires explicit llm_nodes.")
    active_client = llm_client or fake_llm_client
    if active_client is None:
        active_client = build_real_llm_client(model_config or build_model_config_from_app_config())
    return "rule", _node_strategy_map(enabled_nodes), active_client


def _node_strategy_map(enabled_nodes: Iterable[str]) -> dict[str, NodeStrategy]:
    """Convert eval LLM node aliases into graph node strategy overrides."""

    return build_node_strategy_map(LLMNodeStrategyConfig(enabled_nodes=list(enabled_nodes)))


def _job_id(case: EvalCase) -> str:
    """Generate a stable-prefixed eval job id."""

    return f"eval-{case.case_id}-{uuid4()}"


def _query_result_summary(state: AgentState | None) -> dict[str, int | str | None] | None:
    """Return bounded SQL result metadata for follow-up eval context."""

    if state is None or state.sql_result is None:
        return None
    return {
        "row_count": state.sql_result.row_count,
        "column_count": len(state.sql_result.columns),
        "first_column": state.sql_result.columns[0].name if state.sql_result.columns else None,
    }


def _build_file_ecommerce_orders_datasource() -> SQLAlchemyDataSource:
    """Build a file datasource fixture from the bundled demo CSV."""

    source_path = Path("demo") / "ecommerce_orders_demo.csv"
    output_dir = Path(tempfile.mkdtemp(prefix="data-analysis-agent-eval-file-"))
    imported = import_file_to_sqlite(
        source_path=source_path,
        datasource_id="eval-file-ecommerce-orders",
        output_dir=output_dir,
        table_name="orders",
        source_type="eval_fixture",
        max_bytes=1024 * 1024,
    )
    return SQLAlchemyDataSource(
        datasource_id="eval-file-ecommerce-orders",
        url=f"sqlite+pysqlite:///{Path(imported.sqlite_path).as_posix()}",
    )


def _invoke_graph_safely(graph, state: AgentState) -> AgentState:
    """Return runtime state when a graph fails so eval can summarize failures."""

    try:
        return AgentState.model_validate(graph.invoke(state))
    except Exception as exc:
        failed_state = getattr(exc, "state", None)
        if isinstance(failed_state, AgentState):
            return failed_state
        raise


if __name__ == "__main__":
    raise SystemExit(main())

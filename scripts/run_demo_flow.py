"""运行本地电商 demo 的端到端演示流程。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import Field

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api import create_app
from app.harness import LLMNodeStrategyConfig, build_node_strategy_map
from app.workers import InMemoryJobRunner
from llm.config import ModelConfig
from llm.openai_compatible import OpenAICompatibleClient
from persistence import InMemoryArtifactStore, InMemoryCacheStore
from schemas._base import StrictBaseModel
from schemas.analysis_package import AnalysisPackage
from schemas.report import ReportFormat, ReportOutline
from scripts.create_demo_db import (
    DEFAULT_DB_PATH,
    create_demo_data_source,
    create_demo_db,
    inspect_demo_db,
)
from tools.export_tools import (
    propose_dashboard_outline,
    propose_excel_export,
    propose_ppt_outline,
)

DEFAULT_SESSION_ID = "demo-session"
DEFAULT_DIRECT_QUESTION = "Show monthly GMV trend"
DEFAULT_EXPLORATION_QUESTION = "Explore ecommerce performance"
LLM_NODE_CHOICES = ("router", "planner", "sql_drafter", "insight_writer")
CONFIRM_EXPORTS: tuple[
    tuple[str, ReportFormat, Callable[[AnalysisPackage], ReportOutline]], ...
] = (
    ("excel_confirm", ReportFormat.EXCEL, propose_excel_export),
    ("ppt_confirm", ReportFormat.PPT, propose_ppt_outline),
    ("dashboard_confirm", ReportFormat.DASHBOARD, propose_dashboard_outline),
)
SSE_SAFE_STATUSES = {"completed", "failed", "cancelled"}


class DemoFlowSettings(StrictBaseModel):
    """demo flow 的可配置参数。"""

    db_path: Path = DEFAULT_DB_PATH
    session_id: str = DEFAULT_SESSION_ID
    direct_question: str = DEFAULT_DIRECT_QUESTION
    exploration_question: str = DEFAULT_EXPLORATION_QUESTION
    include_sse: bool = True
    llm_nodes: list[str] = Field(default_factory=list)
    provider: str = "openai_compatible"
    model: str | None = None
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 30
    max_retries: int = 1
    temperature: float = 0
    max_tokens: int | None = None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析 demo flow CLI 参数。"""

    parser = argparse.ArgumentParser(description="Run the local ecommerce demo flow.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help="SQLite demo DB path.")
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--direct-question", default=DEFAULT_DIRECT_QUESTION)
    parser.add_argument("--exploration-question", default=DEFAULT_EXPLORATION_QUESTION)
    parser.add_argument("--skip-sse", action="store_true", help="Skip SSE endpoint fetches.")
    parser.add_argument(
        "--llm-node",
        action="append",
        choices=LLM_NODE_CHOICES,
        dest="llm_nodes",
        help="Optional LLM node family to enable. Defaults to rule strategy.",
    )
    parser.add_argument("--provider", default="openai_compatible")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--max-tokens", type=int, default=None)
    return parser.parse_args(argv)


def settings_from_args(args: argparse.Namespace) -> DemoFlowSettings:
    """把 argparse Namespace 转换为结构化 demo flow settings。"""

    return DemoFlowSettings(
        db_path=Path(args.db_path),
        session_id=args.session_id,
        direct_question=args.direct_question,
        exploration_question=args.exploration_question,
        include_sse=not args.skip_sse,
        llm_nodes=list(args.llm_nodes or []),
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        timeout_seconds=args.timeout_seconds,
        max_retries=args.max_retries,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
    )


def run_demo_flow(
    settings: DemoFlowSettings,
    *,
    artifact_store: InMemoryArtifactStore | None = None,
) -> dict[str, Any]:
    """使用 in-process FastAPI + memory runner 执行标准 demo 流程。"""

    create_demo_db(settings.db_path)
    active_artifact_store = artifact_store or InMemoryArtifactStore()
    runner = build_demo_runner(settings, artifact_store=active_artifact_store)

    from fastapi.testclient import TestClient

    client = TestClient(create_app(job_runner=runner))
    steps: list[dict[str, Any]] = []

    context_job = _submit_chat(
        client,
        settings.session_id,
        {"message": "Profile the ecommerce demo database", "command": "profile"},
    )
    steps.append(_summarize_job(client, context_job, include_sse=settings.include_sse))

    direct_job = _submit_chat(
        client,
        settings.session_id,
        {"message": settings.direct_question, "command": "analyze"},
    )
    steps.append(_summarize_job(client, direct_job, include_sse=settings.include_sse))
    analysis_package_payload = _require_analysis_package(direct_job)
    analysis_package = AnalysisPackage.model_validate(analysis_package_payload)

    open_job = _submit_chat(
        client,
        settings.session_id,
        {"message": settings.exploration_question, "command": "explore"},
    )
    steps.append(_summarize_job(client, open_job, include_sse=settings.include_sse))

    report_outline_job = _submit_chat(
        client,
        settings.session_id,
        {
            "message": "Prepare a report outline for the demo analysis",
            "command": "report",
            "analysis_package": analysis_package_payload,
        },
    )
    steps.append(_summarize_job(client, report_outline_job, include_sse=settings.include_sse))

    for confirm_command, _, proposer in CONFIRM_EXPORTS:
        outline = proposer(analysis_package)
        waiting_job = _submit_chat(
            client,
            settings.session_id,
            {
                "message": f"Prepare {confirm_command} export outline",
                "command": "report",
                "analysis_package": analysis_package_payload,
                "report_outline": outline.model_dump(mode="json"),
            },
        )
        confirmed_job = _approve_job(client, waiting_job["job_id"], confirm_command)
        steps.append(_summarize_job(client, confirmed_job, include_sse=settings.include_sse))

    return {
        "db": inspect_demo_db(settings.db_path),
        "strategy": {
            "default": "rule",
            "requested_llm_nodes": settings.llm_nodes,
            "enabled_llm_nodes": build_node_strategy_map(
                LLMNodeStrategyConfig(enabled_nodes=settings.llm_nodes)
            ),
        },
        "steps": steps,
        "artifact_refs": _deduplicate(
            [artifact_ref for step in steps for artifact_ref in step["artifact_refs"]]
        ),
    }


def build_demo_runner(
    settings: DemoFlowSettings,
    *,
    artifact_store: InMemoryArtifactStore | None = None,
) -> InMemoryJobRunner:
    """构造 demo 使用的 memory backend runner。"""

    node_strategies = build_node_strategy_map(
        LLMNodeStrategyConfig(enabled_nodes=settings.llm_nodes)
    )
    return InMemoryJobRunner(
        data_source=create_demo_data_source(db_path=settings.db_path),
        cache_store=InMemoryCacheStore(),
        artifact_store=artifact_store or InMemoryArtifactStore(),
        node_strategies=node_strategies,
        llm_client=_build_optional_llm_client(settings),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口：执行 demo flow 并打印结构化摘要。"""

    settings = settings_from_args(parse_args(argv))
    print(json.dumps(run_demo_flow(settings), indent=2, ensure_ascii=False, default=str))
    return 0


def _build_optional_llm_client(settings: DemoFlowSettings):
    """仅在显式启用 LLM 节点时构造真实 provider client。"""

    if not settings.llm_nodes:
        return None
    if settings.model is None:
        raise ValueError("--model is required when --llm-node is provided.")
    if settings.provider != "openai_compatible":
        raise ValueError(f"Unsupported provider for demo flow: {settings.provider}")
    return OpenAICompatibleClient(
        ModelConfig(
            provider=settings.provider,
            model=settings.model,
            base_url=settings.base_url,
            api_key_env=settings.api_key_env,
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        )
    )


def _submit_chat(client, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """提交 chat job 并返回 JobResponse JSON。"""

    response = client.post(f"/sessions/{session_id}/chat", json=payload)
    response.raise_for_status()
    return response.json()


def _approve_job(client, job_id: str, command: str) -> dict[str, Any]:
    """通过 approve endpoint 执行确认导出 fast-path。"""

    response = client.post(f"/jobs/{job_id}/approve", json={"command": command})
    response.raise_for_status()
    return response.json()


def _summarize_job(
    client,
    job: dict[str, Any],
    *,
    include_sse: bool,
) -> dict[str, Any]:
    """读取 events / SSE 并生成安全的 job 摘要。"""

    job_id = job["job_id"]
    events_response = client.get(f"/jobs/{job_id}/events")
    events_response.raise_for_status()
    events = events_response.json()
    sse_events = (
        _parse_sse_text(client.get(f"/jobs/{job_id}/events/stream").text)
        if include_sse and job["status"] in SSE_SAFE_STATUSES
        else []
    )
    final_state = job.get("final_state") or {}
    return {
        "job_id": job_id,
        "status": job["status"],
        "intent": job["intent"],
        "command": job["command"],
        "final_response": job.get("final_response_text"),
        "error_message": job.get("error_message"),
        "event_count": len(events),
        "events": [event["event_type"] for event in events],
        "sse_event_count": len(sse_events),
        "sse_events": [event["event"] for event in sse_events],
        "errors": final_state.get("errors") or [],
        "artifact_refs": _artifact_refs_from_job(final_state, events),
    }


def _require_analysis_package(job: dict[str, Any]) -> dict[str, Any]:
    """从 Direct Analysis job 中取出 AnalysisPackage payload。"""

    final_state = job.get("final_state") or {}
    analysis_package = final_state.get("analysis_package")
    if analysis_package is None:
        raise ValueError("Direct analysis demo job did not produce an AnalysisPackage.")
    return analysis_package


def _artifact_refs_from_job(
    final_state: dict[str, Any],
    events: list[dict[str, Any]],
) -> list[str]:
    """从 final_state 和 events 中收集 artifact 引用，不读取正文。"""

    refs: list[str] = []
    chart_spec = final_state.get("chart_spec") or {}
    if chart_spec.get("artifact_ref"):
        refs.append(chart_spec["artifact_ref"])
    analysis_package = final_state.get("analysis_package") or {}
    refs.extend(analysis_package.get("artifact_refs") or [])
    report_result = final_state.get("report_result") or {}
    if report_result.get("artifact_ref"):
        refs.append(report_result["artifact_ref"])
    for event in events:
        refs.extend(_artifact_refs_from_payload(event.get("payload") or {}))
    return _deduplicate(refs)


def _artifact_refs_from_payload(payload: dict[str, Any]) -> list[str]:
    """递归提取事件 payload 中的小型 artifact 引用字段。"""

    refs: list[str] = []
    for key, value in payload.items():
        if key == "artifact_ref" and isinstance(value, str):
            refs.append(value)
        elif isinstance(value, dict):
            refs.extend(_artifact_refs_from_payload(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    refs.extend(_artifact_refs_from_payload(item))
    return refs


def _parse_sse_text(text: str) -> list[dict[str, Any]]:
    """解析有限 SSE 响应，供 demo 输出事件名。"""

    frames: list[dict[str, Any]] = []
    for raw_frame in text.strip().split("\n\n"):
        if not raw_frame:
            continue
        event_name = "message"
        data = ""
        for line in raw_frame.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
        frames.append({"event": event_name, "data": json.loads(data) if data else None})
    return frames


def _deduplicate(values: list[str]) -> list[str]:
    """按出现顺序去重。"""

    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            output.append(value)
            seen.add(value)
    return output


if __name__ == "__main__":
    raise SystemExit(main())

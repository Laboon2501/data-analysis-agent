"""Manual real LLM eval runner.

This script is intentionally not used by pytest or CI. It requires explicit
LLM node selection and real provider configuration before network calls happen.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from evals.runner import (  # noqa: E402
    DEFAULT_LLM_NODE_ALIASES,
    LLM_EVAL_CASE_FILE,
    build_model_config_from_app_config,
    run_eval_suite,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse manual LLM eval CLI flags."""

    parser = argparse.ArgumentParser(description="Run optional real LLM eval cases.")
    parser.add_argument(
        "--case-file",
        action="append",
        dest="case_files",
        default=None,
        help="JSONL case file to run. Defaults to evals/cases/llm_eval_cases.jsonl.",
    )
    parser.add_argument(
        "--llm-node",
        action="append",
        choices=DEFAULT_LLM_NODE_ALIASES,
        default=[],
        help="LLM node alias to enable. Can be provided multiple times.",
    )
    parser.add_argument("--provider", help="Override LLM provider from AppConfig/env.")
    parser.add_argument("--model", help="Override LLM model from AppConfig/env.")
    parser.add_argument("--base-url", help="Override OpenAI-compatible base URL.")
    parser.add_argument("--api-key-env", help="Override API key environment variable name.")
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Run only cases with this tag. Can be provided multiple times.",
    )
    parser.add_argument("--output", help="Optional path for raw EvalSummary JSON.")
    return parser.parse_args(argv)


def run_manual_llm_eval(args: argparse.Namespace) -> dict[str, Any]:
    """Run real LLM eval and return a printable summary payload."""

    if not args.llm_node:
        raise RuntimeError("run_llm_eval.py requires at least one --llm-node.")

    model_config = build_model_config_from_app_config(
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
    )
    summary = run_eval_suite(
        case_files=args.case_files or [LLM_EVAL_CASE_FILE],
        strategy="real-llm",
        llm_nodes=args.llm_node,
        output_path=args.output,
        model_config=model_config,
        tags=args.tag,
    )
    return build_printable_summary(summary.model_dump(mode="json"))


def build_printable_summary(summary_payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact manual-eval report from EvalSummary JSON."""

    stats = summary_payload.get("stats") or {}
    failed_cases = [
        {
            "case_id": result.get("case_id"),
            "violations": result.get("violations") or [],
            "metrics": result.get("metrics") or {},
            "stats": result.get("stats") or {},
            "details": result.get("details") or {},
        }
        for result in summary_payload.get("results", [])
        if not result.get("passed")
    ]
    return {
        "summary": {
            "total_cases": summary_payload.get("total_cases"),
            "passed_cases": summary_payload.get("passed_cases"),
            "failed_cases": summary_payload.get("failed_cases"),
            "pass_rate": summary_payload.get("pass_rate"),
            "metric_rates": summary_payload.get("metric_rates"),
        },
        "failed_cases": failed_cases,
        "llm_stats": {
            "llm_call_count": stats.get("llm_call_count", 0),
            "llm_error_count": stats.get("llm_error_count", 0),
            "llm_fallback_count": stats.get("llm_fallback_count", 0),
            "llm_json_invalid_count": stats.get("llm_json_invalid_count", 0),
        },
        "sql_guard_stats": {
            "sql_guard_block_count": stats.get("sql_guard_block_count", 0),
            "generated_sql_valid_rate": stats.get("generated_sql_valid_rate"),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for manual real LLM eval."""

    try:
        payload = run_manual_llm_eval(parse_args(argv))
    except RuntimeError as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if not payload["failed_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests for optional real LLM eval configuration without network calls."""

from __future__ import annotations

import json

import pytest

from app.config import AppConfig
from evals.runner import build_model_config_from_app_config, run_eval_suite
from llm.fake import FakeLLMClient


def test_build_model_config_from_app_config_reads_env_style_fields() -> None:
    """Real LLM eval should build ModelConfig from central AppConfig."""

    config = AppConfig(
        llm_provider="openai_compatible",
        llm_model="configured-model",
        llm_base_url="https://provider.example.com/v1",
        llm_api_key_env="PROVIDER_API_KEY",
    )

    model_config = build_model_config_from_app_config(config)

    assert model_config.provider == "openai_compatible"
    assert model_config.model == "configured-model"
    assert model_config.base_url == "https://provider.example.com/v1"
    assert model_config.api_key_env == "PROVIDER_API_KEY"


def test_build_model_config_requires_model_for_real_llm() -> None:
    """Missing model config should fail before any provider call."""

    with pytest.raises(RuntimeError, match="requires a model"):
        build_model_config_from_app_config(AppConfig(llm_model=None))


def test_real_llm_eval_requires_explicit_llm_nodes(tmp_path) -> None:
    """Real LLM eval should not enable provider calls without selected nodes."""

    case_file = _single_direct_case(tmp_path)

    with pytest.raises(RuntimeError, match="explicit llm_nodes"):
        run_eval_suite(
            case_files=[case_file],
            strategy="real-llm",
            llm_client=FakeLLMClient(),
        )


def test_real_llm_eval_can_use_fake_client_for_selected_node(tmp_path) -> None:
    """Tests can exercise real-llm strategy wiring with FakeLLMClient only."""

    case_file = _single_direct_case(tmp_path)
    fake_client = FakeLLMClient(
        [
            json.dumps(
                {
                    "query": "SELECT SUM(revenue) AS total_revenue FROM orders",
                    "rationale": "Fake LLM SQL for eval.",
                }
            )
        ]
    )

    summary = run_eval_suite(
        case_files=[case_file],
        strategy="real-llm",
        llm_nodes=["sql_drafter"],
        llm_client=fake_client,
    )

    assert summary.failed_cases == 0
    assert len(fake_client.calls) == 1
    assert summary.stats["llm_call_count"] == 1
    assert summary.stats["llm_fallback_count"] == 0
    assert summary.stats["generated_sql_valid_rate"] == 1.0


def _single_direct_case(tmp_path) -> str:
    """Write one small direct-analysis eval case file."""

    case_file = tmp_path / "direct.jsonl"
    case_file.write_text(
        json.dumps(
            {
                "case_id": "real_llm_single_direct",
                "datasource_fixture": "sqlite_orders",
                "user_message": "What is total revenue?",
                "expected_intent": "direct_analysis",
                "expected_sql_contains": ["SUM(revenue)", "FROM orders"],
                "expected_tables": ["orders"],
                "expected_metrics": ["orders.revenue"],
                "expected_chart_type": "table",
                "expected_artifact_types": [],
                "must_not_contain": ["DROP", "Thought:", "Action:"],
                "notes": "Single test case for optional real LLM eval wiring.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return str(case_file)

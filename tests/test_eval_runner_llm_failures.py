"""FakeLLM failure regression tests for the stronger eval suite."""

from __future__ import annotations

import json

from evals.runner import run_eval_suite
from llm.fake import FakeLLMClient


def test_fake_llm_invalid_json_falls_back_without_failing_eval(tmp_path) -> None:
    """Invalid JSON from an LLM node should fallback to rules and keep eval green."""

    summary = run_eval_suite(
        case_files=[_direct_case(tmp_path, case_id="invalid_json_fallback")],
        strategy="real-llm",
        llm_nodes=["sql_drafter"],
        llm_client=FakeLLMClient(["not-json"]),
    )

    assert summary.failed_cases == 0
    assert summary.stats["llm_json_invalid_count"] == 1
    assert summary.stats["llm_fallback_count"] == 1
    assert summary.stats["fallback_rate"] == 1.0


def test_fake_llm_dangerous_sql_is_blocked_and_reported(tmp_path) -> None:
    """Dangerous LLM SQL should be blocked by existing SQLGuard and summarized."""

    summary = run_eval_suite(
        case_files=[_direct_case(tmp_path, case_id="dangerous_sql_block")],
        strategy="real-llm",
        llm_nodes=["sql_drafter"],
        llm_client=FakeLLMClient(
            [json.dumps({"query": "DROP TABLE orders", "rationale": "bad sql"})]
        ),
    )
    result = summary.results[0]

    assert summary.total_cases == 1
    assert summary.failed_cases == 0
    assert summary.stats["llm_fallback_count"] == 1
    assert result.details["fallback_reason"] == ["sql_validation_failed"]
    assert result.details["generated_sql"] == ["SELECT SUM(revenue) AS total_revenue FROM orders"]
    assert "DROP TABLE orders" not in result.details["generated_sql"]


def test_fake_llm_unknown_field_is_reported_without_crashing(tmp_path) -> None:
    """Unknown columns should fail the case, not the entire eval run."""

    summary = run_eval_suite(
        case_files=[_direct_case(tmp_path, case_id="unknown_field")],
        strategy="real-llm",
        llm_nodes=["sql_drafter"],
        llm_client=FakeLLMClient(
            [
                json.dumps(
                    {
                        "query": "SELECT SUM(missing_revenue) AS total FROM orders",
                        "rationale": "bad field",
                    }
                )
            ]
        ),
    )
    result = summary.results[0]

    assert summary.failed_cases == 0
    assert summary.stats["llm_fallback_count"] == 1
    assert result.details["fallback_reason"] == ["sql_validation_failed"]
    assert result.details["sql_validation"]["is_valid"] is True
    assert result.details["generated_sql"] == ["SELECT SUM(revenue) AS total_revenue FROM orders"]


def test_fake_llm_cross_table_field_combo_is_reported(tmp_path) -> None:
    """Cross-table field mistakes should be visible in failure details."""

    summary = run_eval_suite(
        case_files=[_direct_case(tmp_path, case_id="cross_table_field")],
        strategy="real-llm",
        llm_nodes=["sql_drafter"],
        llm_client=FakeLLMClient(
            [
                json.dumps(
                    {
                        "query": (
                            "SELECT region, SUM(revenue) AS total FROM customers GROUP BY region"
                        ),
                        "rationale": "bad table/field combo",
                    }
                )
            ]
        ),
    )
    result = summary.results[0]

    assert summary.failed_cases == 0
    assert summary.stats["llm_fallback_count"] == 1
    assert result.details["fallback_reason"] == ["sql_validation_failed"]
    assert result.details["sql_validation"]["is_valid"] is True
    assert result.details["generated_sql"] == ["SELECT SUM(revenue) AS total_revenue FROM orders"]


def test_fake_llm_empty_insight_falls_back_to_rule(tmp_path) -> None:
    """Empty insight text should trigger fallback and preserve a successful eval."""

    summary = run_eval_suite(
        case_files=[_direct_case(tmp_path, case_id="empty_insight_fallback")],
        strategy="real-llm",
        llm_nodes=["insight_writer"],
        llm_client=FakeLLMClient(
            [json.dumps({"title": "", "summary": "", "evidence": [], "confidence": 0.2})]
        ),
    )
    result = summary.results[0]

    assert summary.failed_cases == 0
    assert summary.stats["llm_fallback_count"] == 1
    assert result.details["fallback_reason"] == ["LLM insight summary must not be empty."]


def _direct_case(tmp_path, *, case_id: str) -> str:
    """Write one reusable direct-analysis eval case."""

    case_file = tmp_path / f"{case_id}.jsonl"
    case_file.write_text(
        json.dumps(
            {
                "case_id": case_id,
                "tags": ["sql"],
                "datasource_fixture": "sqlite_orders",
                "user_message": "What is total revenue?",
                "expected_intent": "direct_analysis",
                "expected_sql_contains": ["orders"],
                "expected_tables": ["orders"],
                "expected_metrics": ["orders.revenue"],
                "expected_chart_type": "table",
                "expected_artifact_types": [],
                "must_not_contain": ["Thought:", "Action:"],
                "notes": "Reusable fake LLM failure regression case.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return str(case_file)

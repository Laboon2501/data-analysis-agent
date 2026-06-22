"""File datasource eval coverage tests."""

from __future__ import annotations

import json

from evals.runner import run_eval_suite


def test_eval_runner_can_analyze_csv_file_datasource(tmp_path) -> None:
    """Eval runner should create a file datasource fixture and run guarded SQL."""

    case_file = tmp_path / "file_cases.jsonl"
    case_file.write_text(
        json.dumps(
            {
                "case_id": "file_csv_trend_eval",
                "tags": ["file-datasource", "trend"],
                "datasource_fixture": "file_ecommerce_orders_csv",
                "user_message": "Show monthly GMV trend",
                "expected_intent": "direct_analysis",
                "expected_sql_contains": ["GROUP BY order_month", "ORDER BY order_month"],
                "expected_tables": ["orders"],
                "expected_metrics": ["orders.gmv"],
                "expected_chart_type": "line",
                "expected_artifact_types": [],
                "must_not_contain": ["Electronics,North,Web", "DROP", "DELETE"],
                "notes": "CSV file datasource eval fixture should not leak file body.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = run_eval_suite(case_files=[case_file])

    assert summary.failed_cases == 0
    assert summary.stats["sql_table_match_rate"] == 1.0
    assert summary.stats["sql_field_match_rate"] == 1.0
    assert summary.stats["generated_sql_valid_rate"] == 1.0


def test_eval_runner_tag_filter_runs_file_datasource_cases_only() -> None:
    """Built-in LLM eval cases should support file-datasource tag filtering."""

    summary = run_eval_suite(
        case_files=["evals/cases/llm_eval_cases.jsonl"],
        tags=["file-datasource"],
    )

    assert summary.total_cases == 2
    assert summary.failed_cases == 0
    assert {result.case_id for result in summary.results} == {
        "llm_file_csv_time_trend",
        "llm_file_csv_top_categories",
    }

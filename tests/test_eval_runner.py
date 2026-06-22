"""Eval runner 测试。"""

import json

from evals.runner import DEFAULT_CASE_FILES, run_eval_suite
from llm.fake import FakeLLMClient


def test_eval_runner_runs_default_suite() -> None:
    """默认 eval suite 应覆盖全部阶段要求的离线 case。"""

    summary = run_eval_suite()
    case_ids = {result.case_id for result in summary.results}

    assert summary.total_cases == 25
    assert summary.passed_cases == 25
    assert summary.failed_cases == 0
    assert summary.metric_rates["intent_accuracy"] == 1.0
    assert summary.stats["router_accuracy"] == 1.0
    assert summary.metric_rates["sql_safety"] == 1.0
    assert "direct_total_revenue" in case_ids
    assert "demo_direct_gmv_trend" in case_ids
    assert "demo_direct_top_categories_cn_profile_join" in case_ids
    assert "demo_followup_average_unit_price_by_category" in case_ids
    assert "demo_open_exploration_semantic_quality" in case_ids
    assert "schema_qa_file_fields" in case_ids
    assert "schema_qa_table_grid_fields" in case_ids
    assert "open_default_revenue_map" in case_ids
    assert "report_monthly_revenue_exports" in case_ids
    assert "router_open_exploratory_cn" in case_ids


def test_eval_runner_writes_summary_json(tmp_path) -> None:
    """Runner 应支持指定 case 文件并写出 summary JSON。"""

    output_path = tmp_path / "summary.json"
    summary = run_eval_suite(
        case_files=[DEFAULT_CASE_FILES[0]],
        output_path=output_path,
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert summary.total_cases == 3
    assert payload["total_cases"] == 3
    assert payload["failed_cases"] == 0
    assert len(payload["results"]) == 3


def test_eval_runner_supports_fake_llm_strategy_without_network() -> None:
    """fake-llm strategy 应使用 FakeLLMClient 并通过 fallback 保持离线成功。"""

    fake_llm_client = FakeLLMClient()

    summary = run_eval_suite(
        case_files=[DEFAULT_CASE_FILES[0]],
        strategy="fake-llm",
        fake_llm_client=fake_llm_client,
    )

    assert summary.failed_cases == 0
    assert len(fake_llm_client.calls) > 0

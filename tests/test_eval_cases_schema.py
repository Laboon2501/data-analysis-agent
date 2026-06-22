"""Eval JSONL case schema 测试。"""

from collections import Counter

from evals.runner import DEFAULT_CASE_FILES, LLM_EVAL_CASE_FILE, load_case_files
from schemas.agent_state import AgentIntent


def test_default_eval_cases_match_schema_and_minimum_coverage() -> None:
    """默认 eval case 文件应可解析，并满足阶段要求的最小覆盖量。"""

    cases = load_case_files(DEFAULT_CASE_FILES)
    case_ids = [case.case_id for case in cases]
    intent_counts = Counter(case.expected_intent for case in cases)

    assert len(case_ids) == len(set(case_ids))
    assert intent_counts[AgentIntent.DIRECT_ANALYSIS] >= 3
    assert intent_counts[AgentIntent.OPEN_EXPLORATION] >= 2
    assert intent_counts[AgentIntent.CONTEXT_MANAGER] >= 1
    assert intent_counts[AgentIntent.REPORT_EXPORT] >= 1
    assert intent_counts[AgentIntent.SCHEMA_QA] >= 4

    for case in cases:
        assert case.datasource_fixture in {
            "sqlite_orders",
            "sqlite_ecommerce_demo",
            "file_ecommerce_orders_csv",
        }
        assert case.user_message
        assert case.notes


def test_report_export_case_declares_expected_artifact_types() -> None:
    """报告导出 case 应显式声明需要生成的 artifact 类型。"""

    cases = load_case_files(DEFAULT_CASE_FILES)
    report_cases = [case for case in cases if case.expected_intent is AgentIntent.REPORT_EXPORT]

    assert report_cases
    assert {artifact_type.value for artifact_type in report_cases[0].expected_artifact_types} == {
        "report",
        "excel",
        "ppt",
    }


def test_llm_eval_cases_are_optional_and_cover_required_shapes() -> None:
    """Optional real LLM cases should be valid without entering the default suite."""

    default_case_ids = {case.case_id for case in load_case_files(DEFAULT_CASE_FILES)}
    llm_cases = load_case_files([LLM_EVAL_CASE_FILE])
    llm_case_ids = {case.case_id for case in llm_cases}
    intent_counts = Counter(case.expected_intent for case in llm_cases)

    assert not (default_case_ids & llm_case_ids)
    assert len(llm_cases) >= 10
    assert intent_counts[AgentIntent.DIRECT_ANALYSIS] >= 2
    assert intent_counts[AgentIntent.OPEN_EXPLORATION] >= 1
    assert intent_counts[AgentIntent.REPORT_EXPORT] >= 1
    assert intent_counts[AgentIntent.CLARIFICATION] >= 3
    assert any("GROUP BY order_month" in case.expected_sql_contains for case in llm_cases)
    assert any("LIMIT 5" in case.expected_sql_contains for case in llm_cases)
    assert any("file-datasource" in case.tags for case in llm_cases)
    assert any("sql-guard" in case.tags for case in llm_cases)

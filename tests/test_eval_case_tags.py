"""Eval case tag filtering tests."""

from __future__ import annotations

from evals.runner import LLM_EVAL_CASE_FILE, filter_cases_by_tags, load_case_files, parse_args


def test_llm_eval_cases_can_filter_by_single_tag() -> None:
    """Tag filtering should keep only cases that explicitly declare the tag."""

    cases = load_case_files([LLM_EVAL_CASE_FILE])
    chat_cases = filter_cases_by_tags(cases, ["chat"])

    assert chat_cases
    assert all("chat" in case.tags for case in chat_cases)


def test_llm_eval_cases_can_filter_by_any_tag() -> None:
    """Multiple tags should behave as an OR filter."""

    cases = load_case_files([LLM_EVAL_CASE_FILE])
    filtered = filter_cases_by_tags(cases, ["file-datasource", "export"])
    case_ids = {case.case_id for case in filtered}

    assert "llm_file_csv_time_trend" in case_ids
    assert "llm_demo_report_exports" in case_ids
    assert all({"file-datasource", "export"}.intersection(case.tags) for case in filtered)


def test_eval_runner_parse_args_accepts_tag_filters() -> None:
    """CLI should support repeated --tag flags."""

    args = parse_args(["--case-file", "evals/cases/llm_eval_cases.jsonl", "--tag", "sql"])

    assert args.tag == ["sql"]

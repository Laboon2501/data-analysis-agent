"""Tests for the manual real LLM eval helper script without network calls."""

from __future__ import annotations

from evals.metrics import EvalCaseResult, EvalSummary
from scripts import run_llm_eval


def test_run_llm_eval_requires_explicit_llm_node(capsys) -> None:
    """Manual script should fail clearly before model/provider setup."""

    exit_code = run_llm_eval.main(["--model", "test-model"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "requires at least one --llm-node" in captured.err


def test_run_llm_eval_passes_real_strategy_to_runner(monkeypatch) -> None:
    """Script should call eval runner with real-llm and selected nodes only."""

    calls = {}

    def fake_run_eval_suite(**kwargs):
        calls.update(kwargs)
        return EvalSummary(
            total_cases=1,
            passed_cases=1,
            failed_cases=0,
            pass_rate=1.0,
            metric_rates={"intent_accuracy": 1.0},
            stats={
                "llm_call_count": 2,
                "llm_error_count": 0,
                "llm_fallback_count": 0,
                "llm_json_invalid_count": 0,
                "sql_guard_block_count": 0,
                "generated_sql_valid_rate": 1.0,
            },
            results=[
                EvalCaseResult(
                    case_id="case-1",
                    passed=True,
                    metrics={"intent_accuracy": True},
                    stats={"llm_call_count": 2},
                    violations=[],
                )
            ],
        )

    monkeypatch.setattr(run_llm_eval, "run_eval_suite", fake_run_eval_suite)

    payload = run_llm_eval.run_manual_llm_eval(
        run_llm_eval.parse_args(
            [
                "--llm-node",
                "sql_drafter",
                "--model",
                "test-model",
                "--base-url",
                "https://provider.example.com/v1",
                "--api-key-env",
                "TEST_PROVIDER_KEY",
                "--tag",
                "sql",
            ]
        )
    )

    assert calls["strategy"] == "real-llm"
    assert calls["llm_nodes"] == ["sql_drafter"]
    assert calls["tags"] == ["sql"]
    assert calls["model_config"].model == "test-model"
    assert calls["model_config"].api_key_env == "TEST_PROVIDER_KEY"
    assert payload["summary"]["failed_cases"] == 0
    assert payload["llm_stats"]["llm_call_count"] == 2
    assert payload["sql_guard_stats"]["generated_sql_valid_rate"] == 1.0


def test_build_printable_summary_lists_failed_cases() -> None:
    """Printable payload should expose failed cases and compact diagnostics."""

    payload = run_llm_eval.build_printable_summary(
        {
            "total_cases": 1,
            "passed_cases": 0,
            "failed_cases": 1,
            "pass_rate": 0.0,
            "metric_rates": {"sql_safety": 0.0},
            "stats": {
                "llm_call_count": 1,
                "llm_error_count": 1,
                "llm_fallback_count": 1,
                "llm_json_invalid_count": 0,
                "sql_guard_block_count": 1,
                "generated_sql_valid_rate": 0.0,
            },
            "results": [
                {
                    "case_id": "failed-case",
                    "passed": False,
                    "metrics": {"sql_safety": False},
                    "stats": {"llm_call_count": 1},
                    "violations": ["sql_safety"],
                    "details": {
                        "actual_intent": "direct_analysis",
                        "generated_sql": ["DROP TABLE orders"],
                    },
                }
            ],
        }
    )

    assert payload["failed_cases"] == [
        {
            "case_id": "failed-case",
            "violations": ["sql_safety"],
            "metrics": {"sql_safety": False},
            "stats": {"llm_call_count": 1},
            "details": {
                "actual_intent": "direct_analysis",
                "generated_sql": ["DROP TABLE orders"],
            },
        }
    ]
    assert payload["llm_stats"]["llm_fallback_count"] == 1
    assert payload["sql_guard_stats"]["sql_guard_block_count"] == 1

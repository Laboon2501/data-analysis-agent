"""Project onboarding documentation and command-entry tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

README = REPO_ROOT / "README.md"
ARCHITECTURE_DOC = REPO_ROOT / "docs" / "architecture.md"
COMMANDS_DOC = REPO_ROOT / "docs" / "commands.md"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

SCRIPT_COMMANDS = (
    "python scripts/create_demo_db.py",
    "python scripts/run_demo_flow.py",
    "python scripts/run_llm_eval.py",
    "python scripts/run_llm_smoke.py",
    "python scripts/run_mcp_smoke.py",
    "python scripts/run_integration_smoke.py",
)


def test_onboarding_docs_cover_required_topics() -> None:
    """README should be a useful project entrypoint for new developers."""

    text = README.read_text(encoding="utf-8")

    for keyword in (
        "Architecture Overview",
        "Directory Structure",
        "Quick Start",
        "Demo Database",
        "FastAPI Memory Backend",
        "Eval And Tests",
        "Optional Smoke Tests",
        "Safety Boundaries",
        "SQLGuard",
        "artifact",
        "fast-path",
    ):
        assert keyword in text


def test_architecture_doc_covers_primary_components() -> None:
    """Architecture docs should describe the implemented graph families."""

    text = ARCHITECTURE_DOC.read_text(encoding="utf-8")

    for keyword in (
        "LangGraph Workflow Overview",
        "Context Manager",
        "Direct Analysis",
        "Open Exploration",
        "Report Export",
        "Artifact, SSE, Worker, Persistence",
        "LLM Strategy Fallback",
        "MCP Adapter",
    ):
        assert keyword in text


def test_commands_doc_and_ci_cover_required_commands() -> None:
    """Command docs and CI should include the release-blocking checks."""

    commands_text = COMMANDS_DOC.read_text(encoding="utf-8")
    ci_text = CI_WORKFLOW.read_text(encoding="utf-8")

    for command in (
        "python -m pytest",
        "python -m evals.runner",
        "python -m ruff check .",
        "python -m ruff format --check .",
        *SCRIPT_COMMANDS,
    ):
        assert command in commands_text

    for command in (
        "python -m ruff check .",
        "python -m ruff format --check .",
        "python -m pytest",
        "python -m evals.runner",
    ):
        assert command in ci_text


def test_manual_script_help_entrypoints_do_not_require_external_services() -> None:
    """Documented scripts should at least expose CLI help without network calls."""

    scripts = (
        "create_demo_db.py",
        "run_demo_flow.py",
        "run_api.py",
        "run_integration_smoke.py",
        "run_llm_eval.py",
        "run_llm_smoke.py",
        "run_mcp_smoke.py",
    )

    for script_name in scripts:
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / script_name), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout

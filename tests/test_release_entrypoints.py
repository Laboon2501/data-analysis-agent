"""Release entrypoint checks for local API and example clients."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dependencies_include_uvicorn_standard() -> None:
    """uvicorn should be installed by the default project dependencies."""

    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert "uvicorn[standard]>=0.34,<1.0" in project["dependencies"]


def test_hatchling_wheel_declares_top_level_runtime_packages() -> None:
    """Editable installs should not depend on project-name package inference."""

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "app",
        "graphs",
        "nodes",
        "schemas",
        "tools",
        "persistence",
        "guards",
        "datasource",
        "llm",
        "mcp",
        "evals",
    ]


def test_install_docs_include_editable_project_install() -> None:
    """Release docs should tell users to install the project before running scripts."""

    for relative_path in ("README.md", "docs/commands.md", "docs/local_run.md"):
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert 'python -m pip install -e ".[dev]"' in text


def test_release_cli_help_entrypoints_run_from_repo_root() -> None:
    """Documented API/client entrypoints should expose --help without import errors."""

    commands = (
        (sys.executable, "scripts/run_api.py", "--help"),
        (sys.executable, "examples/client/minimal_client.py", "--help"),
        (sys.executable, "-m", "examples.client.minimal_client", "--help"),
        (sys.executable, "examples/client/demo_flow_client.py", "--help"),
        (sys.executable, "-m", "examples.client.demo_flow_client", "--help"),
    )

    for command in commands:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout

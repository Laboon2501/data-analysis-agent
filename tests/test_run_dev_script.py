"""run_dev.py local launcher tests."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

from scripts import run_dev


def test_run_dev_parse_args_defaults() -> None:
    """run_dev should default to memory runner, local ports, and persistent history."""

    args = run_dev.parse_args([])

    assert args.api_host == "127.0.0.1"
    assert args.api_port == 8000
    assert args.web_host == "127.0.0.1"
    assert args.web_port == 5173
    assert args.runner_backend == "memory"
    assert args.session_store == "sqlite"
    assert args.session_db_url is None
    assert run_dev.effective_session_db_url(args) == run_dev.default_session_db_url()
    assert args.no_browser is False
    assert args.no_create_demo_db is False


def test_run_dev_parse_args_custom_ports_and_no_browser() -> None:
    """CLI flags should override local startup defaults."""

    args = run_dev.parse_args(
        [
            "--api-port",
            "8010",
            "--web-port",
            "5174",
            "--runner-backend",
            "celery",
            "--session-store",
            "sqlite",
            "--no-browser",
            "--reload",
        ]
    )

    assert run_dev.api_url(args) == "http://127.0.0.1:8010"
    assert run_dev.web_url(args) == "http://127.0.0.1:5174"
    assert args.runner_backend == "celery"
    assert args.session_store == "sqlite"
    assert args.no_browser is True
    assert args.reload is True


def test_build_api_command_reuses_run_api_and_demo_datasource(tmp_path: Path) -> None:
    """The backend command should delegate to scripts/run_api.py."""

    args = run_dev.parse_args(["--api-port", "8010", "--session-store", "sqlite", "--reload"])
    db_path = tmp_path / "demo.sqlite"
    command = run_dev.build_api_command(args, db_path=db_path)

    assert command[0] == sys.executable
    assert str(run_dev.ROOT_DIR / "scripts" / "run_api.py") in command
    assert "--runner-backend" in command
    assert "memory" in command
    assert "--session-store" in command
    assert "sqlite" in command
    assert "--session-db-url" in command
    assert run_dev.default_session_db_url() in command
    assert "--datasource-url" in command
    assert str(db_path) in command
    assert "--datasource-id" in command
    assert run_dev.DEMO_DATASOURCE_ID in command
    assert "--reload" in command


def test_build_web_command_uses_stdlib_http_server() -> None:
    """The Web command should use Python's standard static server."""

    args = run_dev.parse_args(["--web-host", "0.0.0.0", "--web-port", "5174"])

    assert run_dev.build_web_command(args) == [
        sys.executable,
        "-m",
        "http.server",
        "5174",
        "--bind",
        "0.0.0.0",
    ]


def test_port_conflict_messages_detect_same_endpoint() -> None:
    """API and Web should not be allowed to request the same endpoint."""

    args = run_dev.parse_args(["--api-port", "8010", "--web-port", "8010"])

    assert any("both requested" in message for message in run_dev.port_conflict_messages(args))


def test_is_port_available_detects_bound_port() -> None:
    """Port helper should report an already bound port as unavailable."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        host, port = sock.getsockname()

        assert run_dev.is_port_available(host, port) is False


def test_ensure_demo_database_creates_missing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing demo DB should be created unless disabled."""

    created_paths: list[Path] = []

    def fake_create_demo_db(path: Path) -> Path:
        created_paths.append(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")
        return path

    monkeypatch.setattr(run_dev, "create_demo_db", fake_create_demo_db)
    db_path = tmp_path / "nested" / "demo.sqlite"

    assert run_dev.ensure_demo_database(db_path, create_if_missing=True) == db_path
    assert created_paths == [db_path]
    assert db_path.exists()


def test_ensure_demo_database_respects_no_create_demo_db(tmp_path: Path) -> None:
    """--no-create-demo-db should fail clearly when the demo DB is missing."""

    missing_path = tmp_path / "missing.sqlite"

    with pytest.raises(run_dev.DevStartupError, match="Demo database does not exist"):
        run_dev.ensure_demo_database(missing_path, create_if_missing=False)


def test_run_dev_memory_session_store_has_no_session_db_url() -> None:
    """Explicit memory session store should stay temporary and avoid sqlite wiring."""

    args = run_dev.parse_args(["--session-store", "memory"])
    command = run_dev.build_api_command(args, db_path=Path("demo.sqlite"))

    assert args.session_store == "memory"
    assert run_dev.effective_session_db_url(args) is None
    assert "--session-db-url" not in command


def test_ensure_session_db_parent_creates_sqlite_parent(tmp_path: Path) -> None:
    """The run_dev sqlite default should be ready before run_api starts."""

    db_url = f"sqlite:///{(tmp_path / 'nested' / 'sessions.sqlite').as_posix()}"

    run_dev.ensure_session_db_parent(db_url)

    assert (tmp_path / "nested").is_dir()

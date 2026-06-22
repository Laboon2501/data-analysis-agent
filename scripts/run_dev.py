"""One-command local development launcher for API and Web UI."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.create_demo_db import DEMO_DATASOURCE_ID, create_demo_db, inspect_demo_db

DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 8000
DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 5173
DEFAULT_DB_PATH = ROOT_DIR / "demo" / "ecommerce_demo.sqlite"
DEFAULT_SESSION_DB_PATH = ROOT_DIR / "tmp" / "dev_sessions.sqlite"
WEB_DIR = ROOT_DIR / "examples" / "web"
API_HEALTH_TIMEOUT_SECONDS = 30.0
WEB_HEALTH_TIMEOUT_SECONDS = 10.0


class DevStartupError(RuntimeError):
    """Raised when the local development environment cannot be started safely."""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse one-command local development launcher arguments."""

    parser = argparse.ArgumentParser(
        description="Start the local FastAPI backend and static Web UI."
    )
    parser.add_argument("--api-host", default=DEFAULT_API_HOST)
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT)
    parser.add_argument("--web-host", default=DEFAULT_WEB_HOST)
    parser.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT)
    parser.add_argument(
        "--runner-backend",
        choices=("memory", "celery"),
        default="memory",
        help="Backend runner used by scripts/run_api.py.",
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="SQLite demo database path used as the default datasource.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open the Web UI in the default browser.",
    )
    parser.add_argument(
        "--no-create-demo-db",
        action="store_true",
        help="Do not create the demo SQLite database if it is missing.",
    )
    parser.add_argument(
        "--session-store",
        choices=("memory", "sqlite", "sqlalchemy"),
        default="sqlite",
        help="Session history store passed through to scripts/run_api.py.",
    )
    parser.add_argument(
        "--session-db-url",
        default=None,
        help=(
            "SQLite/SQLAlchemy URL for persistent session history. "
            "Defaults to tmp/dev_sessions.sqlite when --session-store=sqlite."
        ),
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Pass uvicorn reload mode through to scripts/run_api.py.",
    )
    return parser.parse_args(argv)


def api_url(args: argparse.Namespace) -> str:
    """Return the backend API base URL."""

    return f"http://{args.api_host}:{args.api_port}"


def web_url(args: argparse.Namespace) -> str:
    """Return the static Web UI base URL."""

    return f"http://{args.web_host}:{args.web_port}"


def is_port_available(host: str, port: int) -> bool:
    """Return whether a host/port can be bound by a new local server."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def port_conflict_messages(args: argparse.Namespace) -> list[str]:
    """Build clear messages for requested port conflicts."""

    messages: list[str] = []
    if args.api_host == args.web_host and args.api_port == args.web_port:
        messages.append(
            f"API and Web UI both requested {args.api_host}:{args.api_port}. "
            "Use --api-port or --web-port to choose different ports."
        )
    if not is_port_available(args.api_host, args.api_port):
        messages.append(
            f"API port {args.api_port} on {args.api_host} is already in use. "
            "Use --api-port to choose another port."
        )
    if not is_port_available(args.web_host, args.web_port):
        messages.append(
            f"Web UI port {args.web_port} on {args.web_host} is already in use. "
            "Use --web-port to choose another port."
        )
    return messages


def ensure_demo_database(db_path: Path | str, *, create_if_missing: bool) -> Path:
    """Ensure the demo SQLite database is present for local startup."""

    candidate_path = Path(db_path)
    resolved_path = (
        (ROOT_DIR / candidate_path).resolve()
        if not candidate_path.is_absolute()
        else candidate_path
    )
    if resolved_path.exists():
        return resolved_path
    if not create_if_missing:
        raise DevStartupError(
            f"Demo database does not exist: {resolved_path}. "
            "Run scripts/create_demo_db.py or omit --no-create-demo-db."
        )
    return create_demo_db(resolved_path)


def build_api_command(args: argparse.Namespace, *, db_path: Path) -> list[str]:
    """Build the backend command while delegating to scripts/run_api.py."""

    session_db_url = effective_session_db_url(args)
    command = [
        sys.executable,
        str(ROOT_DIR / "scripts" / "run_api.py"),
        "--host",
        args.api_host,
        "--port",
        str(args.api_port),
        "--runner-backend",
        args.runner_backend,
        "--session-store",
        args.session_store,
        "--datasource-url",
        str(db_path),
        "--datasource-id",
        DEMO_DATASOURCE_ID,
    ]
    if session_db_url:
        command.extend(["--session-db-url", session_db_url])
    if args.reload:
        command.append("--reload")
    return command


def build_web_command(args: argparse.Namespace) -> list[str]:
    """Build the standard-library static server command."""

    return [
        sys.executable,
        "-m",
        "http.server",
        str(args.web_port),
        "--bind",
        args.web_host,
    ]


def wait_for_http(url: str, *, timeout_seconds: float) -> bool:
    """Poll an HTTP endpoint until it responds or the timeout expires."""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                return 200 <= response.status < 500
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    return False


def terminate_processes(processes: Sequence[subprocess.Popen[object]]) -> None:
    """Terminate child processes gracefully, then force-kill stragglers."""

    for process in processes:
        if process.poll() is None:
            process.terminate()
    for process in processes:
        if process.poll() is None:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def backend_stderr_summary(process: subprocess.Popen[str], *, max_chars: int = 4000) -> str:
    """Read a bounded backend stderr summary after startup failure."""

    if process.stderr is None:
        return ""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    return process.stderr.read()[-max_chars:].strip()


def default_session_db_url() -> str:
    """Return the default local SQLite session store URL for run_dev."""

    return f"sqlite:///{DEFAULT_SESSION_DB_PATH.as_posix()}"


def effective_session_db_url(args: argparse.Namespace) -> str | None:
    """Return the configured session DB URL, if the selected store needs one."""

    if args.session_db_url:
        return args.session_db_url
    if args.session_store == "sqlite":
        return default_session_db_url()
    return None


def ensure_session_db_parent(session_db_url: str | None) -> None:
    """Create the local SQLite session DB parent directory before API startup."""

    if not session_db_url or not session_db_url.startswith("sqlite:///"):
        return
    raw_path = session_db_url.removeprefix("sqlite:///")
    if raw_path in {":memory:", ""}:
        return
    Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def print_startup_summary(args: argparse.Namespace, *, db_path: Path) -> None:
    """Print local development environment startup details."""

    datasource_summary = inspect_demo_db(db_path)
    session_db_url = effective_session_db_url(args)
    print("Starting local Data Analysis Agent development environment")
    print(f"API URL: {api_url(args)}")
    print(f"Web UI URL: {web_url(args)}")
    print(f"Demo DB path: {db_path}")
    print(f"Runner backend: {args.runner_backend}")
    print(f"Session store: {args.session_store}")
    if session_db_url:
        print(f"Session DB URL: {session_db_url}")
    print(f"Datasource ID: {DEMO_DATASOURCE_ID}")
    print(f"Datasource tables: {', '.join(datasource_summary['tables'])}")
    print("Stop: press Ctrl+C")


def main(argv: Sequence[str] | None = None) -> int:
    """Start backend and Web UI processes, then clean them up on Ctrl+C."""

    args = parse_args(argv)
    conflicts = port_conflict_messages(args)
    if conflicts:
        for message in conflicts:
            print(message, file=sys.stderr)
        return 2

    processes: list[subprocess.Popen[str]] = []
    try:
        db_path = ensure_demo_database(
            args.db_path,
            create_if_missing=not args.no_create_demo_db,
        )
        ensure_session_db_parent(effective_session_db_url(args))
        print_startup_summary(args, db_path=db_path)

        api_process = subprocess.Popen(
            build_api_command(args, db_path=db_path),
            cwd=ROOT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        processes.append(api_process)
        if wait_for_http(f"{api_url(args)}/health", timeout_seconds=API_HEALTH_TIMEOUT_SECONDS):
            print("Backend health: OK")
        else:
            summary = backend_stderr_summary(api_process)
            print("Backend health check timed out.", file=sys.stderr)
            if summary:
                print("Backend stderr summary:", file=sys.stderr)
                print(summary, file=sys.stderr)
            return 1

        web_process = subprocess.Popen(
            build_web_command(args),
            cwd=WEB_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        processes.append(web_process)
        if wait_for_http(web_url(args), timeout_seconds=WEB_HEALTH_TIMEOUT_SECONDS):
            print("Web UI static server: OK")
        else:
            print("Web UI static server did not respond in time.", file=sys.stderr)
            return 1

        if not args.no_browser:
            webbrowser.open(web_url(args))
            print("Browser opened.")

        while all(process.poll() is None for process in processes):
            time.sleep(0.5)
        stopped = [process for process in processes if process.poll() is not None]
        if stopped:
            print("A local dev subprocess stopped unexpectedly.", file=sys.stderr)
            return 1
        return 0
    except KeyboardInterrupt:
        print("\nStopping local development environment...")
        return 0
    except DevStartupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        terminate_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())

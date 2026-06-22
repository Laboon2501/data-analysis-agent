"""Dedicated checks for run_dev persistent session defaults."""

from scripts import run_dev


def test_run_dev_defaults_to_sqlite_history_store() -> None:
    """One-command local startup should keep history across API restarts by default."""

    args = run_dev.parse_args([])

    assert args.session_store == "sqlite"
    assert run_dev.effective_session_db_url(args).endswith("/tmp/dev_sessions.sqlite")

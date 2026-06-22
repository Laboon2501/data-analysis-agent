"""Datasource construction helpers for local and distributed runtimes."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import AppConfig
from datasource.sqlalchemy_datasource import SQLAlchemyDataSource


def build_sqlalchemy_data_source(
    config: AppConfig | None = None,
    *,
    default_to_demo: bool = False,
) -> SQLAlchemyDataSource:
    """Build a SQLAlchemyDataSource from config or an explicit demo fallback."""

    active_config = config or AppConfig.from_env()
    datasource_url = active_config.datasource_url
    if not datasource_url:
        if default_to_demo:
            from scripts.create_demo_db import create_demo_data_source

            return create_demo_data_source()
        raise RuntimeError(
            "Datasource configuration is missing. Set DATA_ANALYSIS_AGENT_DATASOURCE_URL "
            "to a SQLite file path or SQLAlchemy URL."
        )

    sqlalchemy_url = datasource_url_to_sqlalchemy_url(datasource_url)
    _validate_sqlite_path_if_needed(sqlalchemy_url)
    return SQLAlchemyDataSource(
        datasource_id=active_config.datasource_id,
        url=sqlalchemy_url,
    )


def datasource_url_to_sqlalchemy_url(datasource_url: str) -> str:
    """Normalize a SQLite file path or SQLAlchemy URL into a SQLAlchemy URL."""

    value = datasource_url.strip()
    if not value:
        raise RuntimeError("Datasource URL cannot be blank.")
    if _looks_like_sqlalchemy_url(value):
        return value
    path = Path(value).expanduser()
    if not path.exists():
        raise RuntimeError(f"Datasource SQLite file does not exist: {path}")
    return f"sqlite+pysqlite:///{path.resolve().as_posix()}"


def _looks_like_sqlalchemy_url(value: str) -> bool:
    """Return whether a value already looks like a SQLAlchemy URL."""

    return "://" in value or value.startswith("sqlite:")


def _validate_sqlite_path_if_needed(sqlalchemy_url: str) -> None:
    """Avoid silently creating an empty SQLite database for missing file paths."""

    parsed_url = make_url(sqlalchemy_url)
    if not parsed_url.drivername.startswith("sqlite"):
        return
    database = parsed_url.database
    if database in {None, "", ":memory:"}:
        return
    if not Path(database).expanduser().exists():
        raise RuntimeError(f"Datasource SQLite file does not exist: {database}")


__all__ = ["build_sqlalchemy_data_source", "datasource_url_to_sqlalchemy_url"]

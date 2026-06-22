"""Datasource factory configuration tests."""

from __future__ import annotations

import pytest

from app.config import AppConfig
from datasource import build_sqlalchemy_data_source, datasource_url_to_sqlalchemy_url
from scripts.create_demo_db import create_demo_db


def test_datasource_factory_accepts_sqlite_file_path(tmp_path) -> None:
    """A plain SQLite file path should become a SQLAlchemy datasource."""

    db_path = create_demo_db(tmp_path / "demo.sqlite")
    config = AppConfig(datasource_url=str(db_path), datasource_id="demo-file")

    data_source = build_sqlalchemy_data_source(config)

    assert data_source.datasource_id == "demo-file"
    assert data_source.dialect == "sqlite"
    assert "orders" in data_source.list_tables()


def test_datasource_factory_accepts_sqlalchemy_url(tmp_path) -> None:
    """A SQLAlchemy URL should be passed through after SQLite path validation."""

    db_path = create_demo_db(tmp_path / "demo.sqlite")
    url = f"sqlite+pysqlite:///{db_path.as_posix()}"
    config = AppConfig(datasource_url=url, datasource_id="demo-url")

    data_source = build_sqlalchemy_data_source(config)

    assert data_source.datasource_id == "demo-url"
    assert data_source.has_table("orders")


def test_datasource_factory_missing_config_fails_clearly() -> None:
    """Missing datasource config should fail unless demo fallback is requested."""

    with pytest.raises(RuntimeError, match="DATA_ANALYSIS_AGENT_DATASOURCE_URL"):
        build_sqlalchemy_data_source(AppConfig(datasource_url=None), default_to_demo=False)


def test_datasource_factory_rejects_missing_sqlite_path(tmp_path) -> None:
    """Missing SQLite files should not be silently created."""

    missing_path = tmp_path / "missing.sqlite"

    with pytest.raises(RuntimeError, match="does not exist"):
        datasource_url_to_sqlalchemy_url(str(missing_path))


def test_datasource_factory_demo_fallback_still_works() -> None:
    """Default local demo datasource should remain available."""

    data_source = build_sqlalchemy_data_source(AppConfig(datasource_url=None), default_to_demo=True)

    assert data_source.datasource_id == "ecommerce-demo-sqlite"
    assert "orders" in data_source.list_tables()

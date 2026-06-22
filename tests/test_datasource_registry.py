"""DatasourceRegistry 的单元测试。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from datasource import DataSourceKind, DataSourceRegistry, DataSourceStatus


def test_registry_registers_sqlite_datasource(tmp_path: Path) -> None:
    """registry 应保存 SQLite 元数据并能构造 datasource。"""

    db_path = _create_sqlite_file(tmp_path / "demo.sqlite")
    registry = DataSourceRegistry()

    record = registry.register(
        datasource_id="demo-sqlite",
        name="Demo SQLite",
        kind=DataSourceKind.SQLITE,
        db_path=str(db_path),
    )

    assert record.datasource_id == "demo-sqlite"
    assert record.kind is DataSourceKind.SQLITE
    assert Path(record.db_path or "").resolve() == db_path.resolve()
    assert record.status is DataSourceStatus.AVAILABLE
    data_source = registry.get_data_source("demo-sqlite")
    assert data_source.list_tables() == ["orders"]


def test_registry_masks_sqlalchemy_password() -> None:
    """SQLAlchemy URL 返回给前端前必须隐藏密码。"""

    registry = DataSourceRegistry()

    record = registry.register(
        datasource_id="warehouse",
        name="Warehouse",
        kind=DataSourceKind.SQLALCHEMY,
        url="postgresql://user:secret@example.com/db",
    )

    assert "secret" not in (record.url or "")
    assert "***" in (record.url or "")


def test_registry_marks_profiled() -> None:
    """profile 成功后应记录 schema hash 和 profile 时间。"""

    registry = DataSourceRegistry()
    registry.register(
        datasource_id="warehouse",
        name="Warehouse",
        kind=DataSourceKind.SQLALCHEMY,
        url="sqlite+pysqlite:///:memory:",
    )

    registry.mark_profiled("warehouse", "abc123")
    record = registry.get_record("warehouse")

    assert record is not None
    assert record.status is DataSourceStatus.PROFILED
    assert record.schema_hash == "abc123"
    assert record.last_profiled_at is not None


def test_registry_snapshot_round_trips_internal_url_without_exposing_password() -> None:
    """Internal snapshots should restore raw URLs while API metadata stays masked."""

    registry = DataSourceRegistry()
    record = registry.register(
        datasource_id="warehouse",
        name="Warehouse",
        kind=DataSourceKind.SQLALCHEMY,
        url="postgresql://user:secret@example.com/db",
    )

    restored = DataSourceRegistry.from_snapshot(registry.to_snapshot())
    restored_record = restored.get_record("warehouse")

    assert restored_record is not None
    assert restored_record.url == record.url
    assert "secret" not in (restored_record.url or "")
    assert "secret" in restored.to_snapshot()["raw_urls"]["warehouse"]


def test_registry_rejects_unsafe_datasource_id(tmp_path: Path) -> None:
    """datasource_id 不允许包含路径或命令分隔符。"""

    db_path = _create_sqlite_file(tmp_path / "demo.sqlite")
    registry = DataSourceRegistry()

    try:
        registry.register(
            datasource_id="../bad",
            name="bad",
            kind=DataSourceKind.SQLITE,
            db_path=str(db_path),
        )
    except ValueError as exc:
        assert "datasource_id" in str(exc)
    else:
        raise AssertionError("unsafe datasource_id should fail")


def _create_sqlite_file(path: Path) -> Path:
    """创建最小 SQLite 文件供 registry 测试使用。"""

    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, revenue REAL)")
        connection.execute("INSERT INTO orders (id, revenue) VALUES (1, 10.0)")
    return path

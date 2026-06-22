"""生成本地电商 SQLite demo database 的脚本。"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from datasource import SQLAlchemyDataSource

DEMO_DIR = ROOT_DIR / "demo"
DEFAULT_SQL_PATH = DEMO_DIR / "ecommerce_demo.sql"
DEFAULT_DB_PATH = DEMO_DIR / "ecommerce_demo.sqlite"
DEMO_DATASOURCE_ID = "ecommerce-demo-sqlite"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析 demo database 生成参数。"""

    parser = argparse.ArgumentParser(description="Create the local ecommerce demo SQLite DB.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database output path.",
    )
    parser.add_argument(
        "--sql-path",
        default=str(DEFAULT_SQL_PATH),
        help="SQL fixture path used to build the database.",
    )
    return parser.parse_args(argv)


def create_demo_db(
    output_path: Path | str = DEFAULT_DB_PATH,
    *,
    sql_path: Path | str = DEFAULT_SQL_PATH,
) -> Path:
    """根据 SQL fixture 可重复生成 SQLite database 文件。"""

    db_path = Path(output_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    sql_text = load_demo_sql(sql_path)
    with sqlite3.connect(db_path) as connection:
        connection.executescript(sql_text)
    return db_path


def create_demo_engine(
    *,
    db_path: Path | str | None = None,
    sql_path: Path | str = DEFAULT_SQL_PATH,
) -> Engine:
    """创建已加载 demo 数据的 SQLAlchemy engine。"""

    if db_path is None:
        engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with engine.begin() as connection:
            raw_connection = connection.connection.driver_connection
            raw_connection.executescript(load_demo_sql(sql_path))
        return engine

    path = create_demo_db(db_path, sql_path=sql_path)
    return create_engine(f"sqlite+pysqlite:///{path.resolve().as_posix()}")


def create_demo_data_source(
    *,
    db_path: Path | str | None = None,
    datasource_id: str = DEMO_DATASOURCE_ID,
) -> SQLAlchemyDataSource:
    """创建供 graph、API runner 和 eval 使用的 demo datasource。"""

    return SQLAlchemyDataSource(
        datasource_id=datasource_id,
        engine=create_demo_engine(db_path=db_path),
        dialect="sqlite",
    )


def load_demo_sql(sql_path: Path | str = DEFAULT_SQL_PATH) -> str:
    """读取 demo SQL fixture。"""

    return Path(sql_path).read_text(encoding="utf-8")


def inspect_demo_db(db_path: Path | str) -> dict[str, object]:
    """返回小型数据库摘要，供 CLI 和测试展示。"""

    path = Path(db_path)
    with sqlite3.connect(path) as connection:
        table_names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        ]
        row_counts = {
            table_name: connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            for table_name in table_names
        }
    return {
        "db_path": str(path),
        "tables": table_names,
        "row_counts": row_counts,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口：生成 demo db 并打印摘要。"""

    args = parse_args(argv)
    db_path = create_demo_db(args.output, sql_path=args.sql_path)
    print(json.dumps(inspect_demo_db(db_path), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

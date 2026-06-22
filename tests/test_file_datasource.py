"""File datasource import tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from datasource.file_datasource import import_file_to_sqlite
from datasource.sqlalchemy_datasource import SQLAlchemyDataSource


def test_csv_file_datasource_imports_to_queryable_sqlite(tmp_path: Path) -> None:
    """CSV files should become read-only-queryable SQLite tables."""

    csv_path = tmp_path / "monthly_orders.csv"
    csv_path.write_text(
        "order_month,gmv,category\n2026-01,100.5,A\n2026-02,210.0,B\n",
        encoding="utf-8",
    )

    imported = import_file_to_sqlite(
        source_path=csv_path,
        datasource_id="monthly-orders",
        output_dir=tmp_path / "uploads",
        table_name="orders",
        max_bytes=1024 * 1024,
    )
    data_source = SQLAlchemyDataSource(
        datasource_id="monthly-orders",
        url=f"sqlite+pysqlite:///{Path(imported.sqlite_path).as_posix()}",
    )

    assert imported.original_filename == "monthly_orders.csv"
    assert imported.table_name == "orders"
    assert imported.row_count == 2
    assert imported.columns == ["order_month", "gmv", "category"]
    assert data_source.has_table("orders") is True
    result = data_source.query("SELECT SUM(gmv) AS total_gmv FROM orders")
    assert result.rows == [{"total_gmv": 310.5}]


def test_excel_file_datasource_imports_first_sheet(tmp_path: Path) -> None:
    """xlsx files should import the first worksheet using cached cell values."""

    xlsx_path = tmp_path / "orders.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["order_month", "gmv"])
    worksheet.append(["2026-01", 100])
    worksheet.append(["2026-02", 210])
    workbook.save(xlsx_path)

    imported = import_file_to_sqlite(
        source_path=xlsx_path,
        datasource_id="excel-orders",
        output_dir=tmp_path / "uploads",
        table_name="orders",
    )
    data_source = SQLAlchemyDataSource(
        datasource_id="excel-orders",
        url=f"sqlite+pysqlite:///{Path(imported.sqlite_path).as_posix()}",
    )

    assert imported.source_type == "path"
    assert imported.row_count == 2
    assert data_source.query("SELECT COUNT(*) AS row_count FROM orders").rows == [{"row_count": 2}]


def test_file_datasource_rejects_unsupported_extension(tmp_path: Path) -> None:
    """Unsupported file extensions should fail before any SQLite import."""

    text_path = tmp_path / "orders.txt"
    text_path.write_text("not,a,datasource\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported file datasource type"):
        import_file_to_sqlite(
            source_path=text_path,
            datasource_id="bad",
            output_dir=tmp_path / "uploads",
        )


def test_file_datasource_rejects_sensitive_environment_files(tmp_path: Path) -> None:
    """Obvious environment files should not be readable as datasources."""

    env_path = tmp_path / ".env"
    env_path.write_text("SECRET=value\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Sensitive environment files"):
        import_file_to_sqlite(
            source_path=env_path,
            datasource_id="env",
            output_dir=tmp_path / "uploads",
        )

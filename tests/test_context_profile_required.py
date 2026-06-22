"""DatabaseProfile requirement tests for analysis graphs."""

from __future__ import annotations

from pathlib import Path

from datasource import SQLAlchemyDataSource
from datasource.file_datasource import import_file_to_sqlite
from graphs.analysis_graph import build_analysis_graph
from schemas import AgentState
from tests.phase49_sql_helpers import CATEGORY_GMV_QUESTION, category_gmv_data_source


def test_analysis_graph_profiles_datasource_before_sql_when_profile_missing() -> None:
    """The graph should build DatabaseProfile before drafting SQL."""

    data_source = category_gmv_data_source()
    result = AgentState.model_validate(
        build_analysis_graph(data_source=data_source).invoke(
            AgentState(
                session_id="session-1",
                job_id="job-1",
                user_message=CATEGORY_GMV_QUESTION,
                datasource_id=data_source.datasource_id,
            )
        )
    )

    assert result.database_profile is not None
    assert result.sql_draft is not None
    assert result.sql_validation is not None and result.sql_validation.is_valid is True
    assert "orders.category" not in result.sql_draft.query
    assert "orders.gmv" not in result.sql_draft.query


def test_file_datasource_analysis_uses_profile_constrained_fields(tmp_path: Path) -> None:
    """File datasources should also profile before rule SQL generation."""

    csv_path = tmp_path / "orders.csv"
    csv_path.write_text(
        "order_month,category,gmv\n2026-01,A,10\n2026-02,A,15\n2026-02,B,5\n",
        encoding="utf-8",
    )
    imported = import_file_to_sqlite(
        source_path=csv_path,
        datasource_id="orders-file",
        output_dir=tmp_path,
        table_name="orders",
    )
    data_source = SQLAlchemyDataSource(
        datasource_id="orders-file",
        url=f"sqlite+pysqlite:///{Path(imported.sqlite_path).as_posix()}",
        dialect="sqlite",
    )
    result = AgentState.model_validate(
        build_analysis_graph(data_source=data_source).invoke(
            AgentState(
                session_id="session-1",
                job_id="job-1",
                user_message=CATEGORY_GMV_QUESTION,
                datasource_id=data_source.datasource_id,
            )
        )
    )

    assert result.database_profile is not None
    assert result.sql_draft is not None
    assert "orders.category" in result.sql_draft.used_fields
    assert "orders.gmv" in result.sql_draft.used_fields
    assert result.sql_result is not None and result.sql_result.row_count > 0

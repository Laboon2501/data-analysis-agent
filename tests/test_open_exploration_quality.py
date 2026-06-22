"""Quality checks for open exploration topic selection and summaries."""

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from datasource import SQLAlchemyDataSource
from graphs.open_exploration_graph import build_open_exploration_graph
from persistence import InMemoryCacheStore
from schemas import AgentState


def test_open_exploration_prefers_semantic_fields_over_anonymous_columns() -> None:
    """开放探索应优先使用 pos/qtd/week/reseller 等有语义字段。"""

    data_source = _semantic_file_like_source()
    result = AgentState.model_validate(
        build_open_exploration_graph(
            data_source=data_source,
            cache_store=InMemoryCacheStore(),
            top_n=3,
        ).invoke(
            AgentState(
                session_id="session-quality",
                job_id="job-quality",
                user_message="帮我看看这张表有什么可以分析的",
                datasource_id=data_source.datasource_id,
            )
        )
    )

    assert result.final_response_text is not None
    assert "已完成开放探索，自动分析了" in result.final_response_text
    assert "pos" in result.final_response_text or "qtd" in result.final_response_text
    assert "column_12 汇总" not in result.final_response_text
    assert "column_9 汇总" not in result.final_response_text
    assert result.exploration_findings
    assert all(
        not (finding.title or "").startswith(("column_12 汇总", "column_9 汇总"))
        for finding in result.exploration_findings
    )
    assert any(finding.result_summary for finding in result.exploration_findings)
    assert any(finding.business_interpretation for finding in result.exploration_findings)


def _semantic_file_like_source() -> SQLAlchemyDataSource:
    """Create a file-like table with semantic and anonymous numeric columns."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE sales_sheet (
                    week TEXT,
                    reseller_name TEXT,
                    hq TEXT,
                    pos REAL,
                    qtd REAL,
                    column_9 REAL,
                    column_12 REAL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO sales_sheet
                    (week, reseller_name, hq, pos, qtd, column_9, column_12)
                VALUES
                    ('2026-W01', 'A reseller', 'North HQ', 120, 20, 999, 888),
                    ('2026-W02', 'B reseller', 'South HQ', 210, 25, 777, 666),
                    ('2026-W03', 'A reseller', 'North HQ', 160, 30, 555, 444)
                """
            )
        )
    return SQLAlchemyDataSource(
        datasource_id="semantic-sheet",
        engine=engine,
        dialect="sqlite",
    )

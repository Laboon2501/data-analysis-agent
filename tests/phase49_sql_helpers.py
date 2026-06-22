"""Shared helpers for Phase 49 SQL hardening tests."""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from datasource import SQLAlchemyDataSource
from graphs.context_manager_graph import build_context_manager_graph
from schemas import AgentState

CATEGORY_GMV_QUESTION = "\u5404\u54c1\u7c7b GMV Top 5 \u662f\u4ec0\u4e48\uff1f"


def category_gmv_data_source() -> SQLAlchemyDataSource:
    """Build a schema where category and GMV require profiled fields and a join."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE products (
                    id INTEGER PRIMARY KEY,
                    category TEXT NOT NULL,
                    unit_price REAL NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE order_items (
                    id INTEGER PRIMARY KEY,
                    product_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    FOREIGN KEY(product_id) REFERENCES products(id)
                )
                """
            )
        )
        connection.execute(
            text("INSERT INTO products (id, category, unit_price) VALUES (1, 'A', 10), (2, 'B', 5)")
        )
        connection.execute(
            text(
                """
                INSERT INTO order_items (id, product_id, quantity)
                VALUES (1, 1, 3), (2, 1, 2), (3, 2, 4)
                """
            )
        )
    return SQLAlchemyDataSource(datasource_id="category-gmv", engine=engine, dialect="sqlite")


def profiled_state(
    data_source: SQLAlchemyDataSource, question: str = CATEGORY_GMV_QUESTION
) -> AgentState:
    """Return state with a Context Manager produced DatabaseProfile."""

    state = AgentState(
        session_id="session-1",
        job_id="job-1",
        user_message=question,
        datasource_id=data_source.datasource_id,
    )
    return AgentState.model_validate(
        build_context_manager_graph(data_source=data_source).invoke(state)
    )

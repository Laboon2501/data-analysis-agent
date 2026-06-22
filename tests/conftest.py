"""Shared pytest configuration and datasource fixtures."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from datasource import SQLAlchemyDataSource


@pytest.fixture
def sqlite_engine():
    """Create an in-memory SQLite engine with stable test tables."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE customers (
                    id INTEGER PRIMARY KEY,
                    region TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY,
                    customer_id INTEGER NOT NULL,
                    month TEXT NOT NULL,
                    revenue REAL NOT NULL,
                    FOREIGN KEY(customer_id) REFERENCES customers(id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO customers (id, region)
                VALUES (1, 'north'), (2, 'south')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO orders (id, customer_id, month, revenue)
                VALUES
                    (1, 1, '2026-01', 100.0),
                    (2, 1, '2026-02', 120.0),
                    (3, 2, '2026-02', 90.0)
                """
            )
        )
    return engine


@pytest.fixture
def sqlite_data_source(sqlite_engine):
    """Return a SQLAlchemyDataSource backed by the in-memory SQLite engine."""

    return SQLAlchemyDataSource(
        datasource_id="test-sqlite",
        engine=sqlite_engine,
        dialect="sqlite",
    )

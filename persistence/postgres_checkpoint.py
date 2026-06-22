"""SQLAlchemy-backed CheckpointStore for Postgres-compatible databases."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, and_, create_engine, select
from sqlalchemy.engine import Engine

from schemas._base import utc_now
from schemas.agent_state import AgentState

POSTGRES_URL_ENV = "DATA_ANALYSIS_AGENT_POSTGRES_URL"
POSTGRES_TABLE_ENV = "DATA_ANALYSIS_AGENT_CHECKPOINT_TABLE"
DEFAULT_TABLE_NAME = "agent_checkpoints"


class PostgresCheckpointStore:
    """CheckpointStore backed by a minimal SQLAlchemy table."""

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        url: str | None = None,
        table_name: str | None = None,
        create_tables: bool = True,
    ) -> None:
        self.engine = engine or create_engine(url or _postgres_url_from_env())
        self.metadata = MetaData()
        self.table = _checkpoint_table(
            self.metadata,
            table_name or os.getenv(POSTGRES_TABLE_ENV, DEFAULT_TABLE_NAME),
        )
        if create_tables:
            self.metadata.create_all(self.engine)

    @classmethod
    def from_env(cls) -> PostgresCheckpointStore:
        """Build a checkpoint store using environment configuration."""

        return cls()

    def save_checkpoint(self, state: AgentState, status: str = "checkpointed") -> None:
        """Persist one AgentState JSON snapshot keyed by session and job."""

        now = utc_now()
        values = {
            "session_id": state.session_id,
            "job_id": state.job_id,
            "status": status,
            "state_json": state.model_dump(mode="json"),
            "updated_at": now,
        }
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(self.table.c.job_id).where(
                    and_(
                        self.table.c.session_id == state.session_id,
                        self.table.c.job_id == state.job_id,
                    )
                )
            ).first()
            if existing is None:
                connection.execute(
                    self.table.insert().values(
                        **values,
                        created_at=now,
                    )
                )
                return
            connection.execute(
                self.table.update()
                .where(
                    and_(
                        self.table.c.session_id == state.session_id,
                        self.table.c.job_id == state.job_id,
                    )
                )
                .values(**values)
            )

    def load_checkpoint(self, session_id: str, job_id: str) -> AgentState | None:
        """Load one AgentState snapshot by session and job."""

        with self.engine.begin() as connection:
            row = connection.execute(
                select(self.table.c.state_json).where(
                    and_(
                        self.table.c.session_id == session_id,
                        self.table.c.job_id == job_id,
                    )
                )
            ).first()
        if row is None:
            return None
        payload = row.state_json
        if isinstance(payload, str):
            return AgentState.model_validate_json(payload)
        return AgentState.model_validate(payload)


def _checkpoint_table(metadata: MetaData, table_name: str) -> Table:
    """Build the checkpoint metadata table."""

    return Table(
        table_name,
        metadata,
        Column("session_id", String(200), primary_key=True),
        Column("job_id", String(200), primary_key=True),
        Column("status", String(80), nullable=False),
        Column("state_json", JSON, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )


def _postgres_url_from_env() -> str:
    """Return Postgres URL from project-specific or common environment variables."""

    url = os.getenv(POSTGRES_URL_ENV) or os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            f"PostgresCheckpointStore requires {POSTGRES_URL_ENV}, POSTGRES_URL, or DATABASE_URL."
        )
    return url


def checkpoint_row_to_dict(row: Any) -> dict[str, Any]:
    """Return a plain dict for tests or future admin tooling."""

    return {
        "session_id": row.session_id,
        "job_id": row.job_id,
        "status": row.status,
        "created_at": _datetime_or_none(row.created_at),
        "updated_at": _datetime_or_none(row.updated_at),
    }


def _datetime_or_none(value: Any) -> datetime | None:
    """Return datetime values unchanged and normalize nulls."""

    return value if isinstance(value, datetime) else None

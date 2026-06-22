"""Factory helpers for configured SessionStore implementations."""

from __future__ import annotations

from app.config import AppConfig
from app.sessions.base import SessionStore
from app.sessions.sqlalchemy_store import SQLAlchemySessionStore
from app.sessions.store import InMemorySessionStore


def build_session_store(config: AppConfig | None = None) -> SessionStore:
    """Build the configured session store without changing graph behavior."""

    active_config = config or AppConfig.from_env()
    if active_config.session_store == "memory":
        return InMemorySessionStore(
            ttl_days=active_config.session_ttl_days,
            max_messages=active_config.session_max_messages,
        )
    if active_config.session_store in {"sqlite", "sqlalchemy"}:
        if not active_config.session_db_url:
            raise RuntimeError(
                "DATA_ANALYSIS_AGENT_SESSION_DB_URL is required when "
                "DATA_ANALYSIS_AGENT_SESSION_STORE is sqlite or sqlalchemy."
            )
        return SQLAlchemySessionStore(
            url=active_config.session_db_url,
            ttl_days=active_config.session_ttl_days,
            max_messages=active_config.session_max_messages,
        )
    raise RuntimeError(f"Unsupported session store: {active_config.session_store}")

"""Session retention cleanup tests."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.sessions import ChatRole, InMemorySessionStore, SessionStore, SQLAlchemySessionStore


@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
def test_cleanup_deletes_expired_sessions_but_respects_exclusions(
    store_kind: str,
    tmp_path,
) -> None:
    """TTL cleanup should not delete explicitly excluded active sessions."""

    store = _store(store_kind, tmp_path)
    old = store.create_session(session_id="old-session")
    store.create_session(session_id="keep-session")

    result = store.cleanup_expired_sessions(
        ttl_days=0,
        exclude_session_ids=["keep-session"],
        now=old.updated_at + timedelta(seconds=1),
    )

    assert result.deleted_sessions == 1
    assert store.get_session("old-session") is None
    assert store.get_session("keep-session") is not None


@pytest.mark.parametrize("store_kind", ["memory", "sqlite"])
def test_cleanup_trims_old_messages_but_keeps_artifact_refs(
    store_kind: str,
    tmp_path,
) -> None:
    """max_messages cleanup should keep recent messages and preserve artifact refs."""

    store = _store(store_kind, tmp_path)
    for index in range(4):
        store.add_message(
            "trim-session",
            role=ChatRole.USER,
            content=f"message-{index}",
            artifact_refs=[f"artifact:chart-{index}"],
        )

    result = store.cleanup_expired_sessions(max_messages=2)
    messages = store.list_messages("trim-session")
    record = store.get_session("trim-session")

    assert result.trimmed_messages == 2
    assert [message.content for message in messages] == ["message-2", "message-3"]
    assert record is not None
    assert record.message_count == 2
    assert record.artifact_refs == [
        "artifact:chart-0",
        "artifact:chart-1",
        "artifact:chart-2",
        "artifact:chart-3",
    ]


def _store(kind: str, tmp_path) -> SessionStore:
    if kind == "memory":
        return InMemorySessionStore()
    return SQLAlchemySessionStore(url=f"sqlite:///{tmp_path / 'sessions.sqlite'}")

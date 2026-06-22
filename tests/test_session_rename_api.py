"""Session rename API tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import create_app
from app.sessions import InMemorySessionStore, SessionTitleSource


def test_patch_session_renames_visible_title() -> None:
    """PATCH /sessions/{session_id} should update title without changing session id."""

    client = TestClient(create_app(session_store=InMemorySessionStore()))
    client.post("/sessions", json={"session_id": "rename-me"})

    response = client.patch("/sessions/rename-me", json={"title": "销售趋势复盘"})
    session = client.get("/sessions/rename-me").json()

    assert response.status_code == 200
    assert response.json()["session_id"] == "rename-me"
    assert response.json()["title"] == "销售趋势复盘"
    assert session["title_source"] == SessionTitleSource.USER.value


def test_patch_session_unknown_returns_404() -> None:
    """Unknown sessions should not be created by rename calls."""

    client = TestClient(create_app(session_store=InMemorySessionStore()))

    response = client.patch("/sessions/missing", json={"title": "Missing"})

    assert response.status_code == 404

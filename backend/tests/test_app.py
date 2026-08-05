"""Tests for the global exception handler (api/app.py)."""
from fastapi import HTTPException
from fastapi.testclient import TestClient

from interview_bot.api.app import app
from interview_bot.persistence import schema


def _client(monkeypatch) -> TestClient:
    # Lifespan calls schema.initialize(), which needs a real Postgres — not
    # available (or wanted) in the offline test gate.
    monkeypatch.setattr(schema, "initialize", lambda: None)
    return TestClient(app, raise_server_exceptions=False)


def test_unhandled_exception_returns_a_sanitized_500(monkeypatch):
    @app.get("/__test/boom")
    def _boom():
        raise RuntimeError("db connection string: postgres://secret@host/db")

    with _client(monkeypatch) as client:
        response = client.get("/__test/boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "secret" not in response.text


def test_http_exception_passes_through_unchanged(monkeypatch):
    @app.get("/__test/not-found")
    def _not_found():
        raise HTTPException(status_code=404, detail="Session not found")

    with _client(monkeypatch) as client:
        response = client.get("/__test/not-found")

    assert response.status_code == 404
    assert response.json() == {"detail": "Session not found"}

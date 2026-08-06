"""Tests for the Google login/logout/me routes (api/routes/auth.py).

Uses a real, ephemeral SQLite database for the two tables these routes touch
(User, UserSession) rather than mocking the ORM session, since the flow spans
a commit + a second lookup — TestClient exercises the actual dependency chain.
"""
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from interview_bot.api.app import app
from interview_bot.integrations import google_auth
from interview_bot.persistence import database
from interview_bot.persistence import schema as schema_module
from interview_bot.persistence.models import Base, User, UserSession


@pytest.fixture
def client(monkeypatch) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Only the auth tables are needed here; the full metadata includes a
    # pgvector column (CVChunk) that SQLite cannot create.
    Base.metadata.create_all(engine, tables=[User.__table__, UserSession.__table__])
    test_session_local = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        db = test_session_local()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(schema_module, "initialize", lambda: None)
    app.dependency_overrides[database.get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _mock_identity(monkeypatch, *, sub="google-sub-1", email="jane@example.com"):
    identity = google_auth.GoogleIdentity(sub=sub, email=email, name="Jane Doe", picture=None)
    monkeypatch.setattr(google_auth, "verify", lambda token: identity)


def test_login_sets_a_session_cookie_and_returns_the_user(client, monkeypatch):
    _mock_identity(monkeypatch)

    response = client.post("/api/auth/google", json={"id_token": "whatever"})

    assert response.status_code == 200
    assert response.json()["email"] == "jane@example.com"
    assert "interview_bot_session" in response.cookies


def test_login_grants_signup_credits_only_once(client, monkeypatch):
    _mock_identity(monkeypatch)

    first = client.post("/api/auth/google", json={"id_token": "whatever"})
    granted = first.json()["credits"]
    assert granted > 0

    second = client.post("/api/auth/google", json={"id_token": "whatever"})
    assert second.json()["credits"] == granted


def test_me_requires_login(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_returns_the_logged_in_user(client, monkeypatch):
    _mock_identity(monkeypatch)
    client.post("/api/auth/google", json={"id_token": "whatever"})

    response = client.get("/api/auth/me")

    assert response.status_code == 200
    assert response.json()["email"] == "jane@example.com"


def test_logout_clears_the_session_even_without_a_prior_login(client):
    response = client.post("/api/auth/logout")
    assert response.status_code == 204


def test_logout_then_me_is_unauthorized(client, monkeypatch):
    _mock_identity(monkeypatch)
    client.post("/api/auth/google", json={"id_token": "whatever"})

    client.post("/api/auth/logout")
    response = client.get("/api/auth/me")

    assert response.status_code == 401


def test_concurrent_first_login_recovers_instead_of_500ing(client, monkeypatch):
    """Two racing first-logins for the same brand-new Google account both try
    to insert the same google_sub; the DB's unique constraint lets only one
    win. The loser must recover to the winner's row, not surface a 500."""
    _mock_identity(monkeypatch, sub="racer", email="racer@example.com")

    first = client.post("/api/auth/google", json={"id_token": "whatever"})
    assert first.status_code == 200

    # Simulate a second concurrent "new user" insert for the same google_sub
    # arriving after the first already committed — get_or_create's own
    # lookup would normally catch this, but forcing it closed exercises the
    # IntegrityError recovery path the same race would actually hit.
    import uuid

    from interview_bot.api.routes import auth as auth_routes
    from interview_bot.persistence.models import User

    def fake_get_or_create(db, **kwargs):
        user = User(
            id=str(uuid.uuid4()),
            google_sub="racer",
            email="racer@example.com",
            display_name=None,
            picture_url=None,
        )
        db.add(user)
        return user, True

    monkeypatch.setattr(auth_routes.user_store, "get_or_create", fake_get_or_create)

    second = client.post("/api/auth/google", json={"id_token": "whatever"})

    assert second.status_code == 200
    assert second.json()["email"] == "racer@example.com"


def test_invalid_google_token_is_rejected(client, monkeypatch):
    def _reject(token):
        raise google_auth.GoogleTokenError("bad token")

    monkeypatch.setattr(google_auth, "verify", _reject)

    response = client.post("/api/auth/google", json={"id_token": "whatever"})

    assert response.status_code == 401

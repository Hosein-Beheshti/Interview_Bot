"""Tests for session creation/deletion requiring login and credits
(api/routes/sessions.py). Same SQLite-backed TestClient approach as
test_auth_routes.py — real commit/lookup flow, not a mocked ORM session.
"""
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from interview_bot.api.app import app
from interview_bot.api.routes import sessions as sessions_route
from interview_bot.config import settings
from interview_bot.domain.profile import JobProfile
from interview_bot.integrations import google_auth
from interview_bot.persistence import database
from interview_bot.persistence import schema as schema_module
from interview_bot.persistence.models import (
    AnswerScore,
    Base,
    InterviewSession,
    User,
    UserSession,
)


@pytest.fixture
def client(monkeypatch) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            UserSession.__table__,
            InterviewSession.__table__,
            # session_store.delete() erases recorded judgements too.
            AnswerScore.__table__,
        ],
    )
    # cv_chunks uses pgvector's Vector type, which SQLite can't create via
    # create_all; session_store.delete() touches this table too, so a plain
    # stand-in (no vector column needed for these tests) is enough.
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE cv_chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "session_id VARCHAR)"
            )
        )
    test_session_local = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db():
        db = test_session_local()
        try:
            yield db
        finally:
            db.close()

    async def _fake_build_profile(job_context):
        return JobProfile(role="Software Engineer")

    async def _fake_build_plan(profile, num_questions):
        return None

    monkeypatch.setattr(schema_module, "initialize", lambda: None)
    monkeypatch.setattr(sessions_route, "build_profile", _fake_build_profile)
    monkeypatch.setattr(sessions_route, "build_plan", _fake_build_plan)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[database.get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, monkeypatch, *, sub: str, email: str) -> None:
    identity = google_auth.GoogleIdentity(sub=sub, email=email, name=None, picture=None)
    monkeypatch.setattr(google_auth, "verify", lambda token: identity)
    client.post("/api/auth/google", json={"id_token": "whatever"})


# --------------------------------------------------------------------------- #
# POST /sessions
# --------------------------------------------------------------------------- #
def test_create_session_requires_login(client):
    response = client.post("/api/sessions", json={"job_context": "Backend role."})
    assert response.status_code == 401


def test_create_session_succeeds_and_sets_the_owner(client, monkeypatch):
    _login(client, monkeypatch, sub="sub-1", email="jane@example.com")

    response = client.post("/api/sessions", json={"job_context": "Backend role."})

    assert response.status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["credits"] == settings.signup_credit_grant - settings.interview_session_credit_cost


def test_create_session_rejects_when_credits_are_exhausted(client, monkeypatch):
    monkeypatch.setattr(settings, "signup_credit_grant", 0)
    _login(client, monkeypatch, sub="sub-2", email="broke@example.com")

    response = client.post("/api/sessions", json={"job_context": "Backend role."})

    assert response.status_code == 402


# --------------------------------------------------------------------------- #
# DELETE /sessions/{id}
# --------------------------------------------------------------------------- #
def test_delete_session_requires_login(client):
    response = client.delete("/api/sessions/some-id")
    assert response.status_code == 401


def test_delete_session_by_a_non_owner_is_forbidden(client, monkeypatch):
    _login(client, monkeypatch, sub="owner", email="owner@example.com")
    session_id = client.post("/api/sessions", json={"job_context": "Backend role."}).json()[
        "session_id"
    ]
    client.post("/api/auth/logout")

    _login(client, monkeypatch, sub="intruder", email="intruder@example.com")
    response = client.delete(f"/api/sessions/{session_id}")

    assert response.status_code == 403


def test_delete_session_by_its_owner_succeeds(client, monkeypatch):
    _login(client, monkeypatch, sub="owner-2", email="owner2@example.com")
    session_id = client.post("/api/sessions", json={"job_context": "Backend role."}).json()[
        "session_id"
    ]

    response = client.delete(f"/api/sessions/{session_id}")

    assert response.status_code == 204

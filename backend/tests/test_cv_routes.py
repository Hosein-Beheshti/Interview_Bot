"""Tests for the CV upload minimum-text rule, end to end.

Same SQLite-backed TestClient approach as test_sessions_routes.py. The rule is
`cv_min_chars`, enforced once in `integrations/cv_parser.parse`; these tests cover
it through `/cv/upload`, where it matters — a CV too thin to ground a question is
rejected *before* the session exists, because creating one is what spends credits.
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
from interview_bot.retrieval import rag


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
            AnswerScore.__table__,
        ],
    )
    # cv_chunks uses pgvector's Vector type, which SQLite cannot create.
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

    async def _fake_index_cv(session_id, parsed):
        # Indexing would embed via Voyage; the rule under test runs before it.
        return rag.IndexResult(chunk_count=1, sections=["Experience"])

    monkeypatch.setattr(schema_module, "initialize", lambda: None)
    monkeypatch.setattr(sessions_route, "build_profile", _fake_build_profile)
    monkeypatch.setattr(sessions_route, "build_plan", _fake_build_plan)
    monkeypatch.setattr(rag, "index_cv", _fake_index_cv)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[database.get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, monkeypatch, *, sub: str = "sub-1", email: str = "jane@example.com") -> None:
    identity = google_auth.GoogleIdentity(sub=sub, email=email, name=None, picture=None)
    monkeypatch.setattr(google_auth, "verify", lambda token: identity)
    client.post("/api/auth/google", json={"id_token": "whatever"})


def _upload(client, text_body: str):
    return client.post(
        "/api/cv/upload",
        files={"file": ("cv.txt", text_body.encode(), "text/plain")},
        data={"role": "Software Engineer"},
    )


def test_a_cv_below_the_minimum_is_rejected(client, monkeypatch):
    _login(client, monkeypatch)

    response = _upload(client, "Too short to interview on.")

    # 400 from the parser's CVParseError — one minimum-text rule, not a second one
    # bolted onto the route with a different status.
    assert response.status_code == 400
    assert str(settings.cv_min_chars) in response.json()["detail"]


def test_rejection_happens_before_any_credit_is_spent(client, monkeypatch):
    # The reason the check sits after parsing but before `_resolve_session`: that
    # call creates the session, and creating one is what debits credits.
    _login(client, monkeypatch)
    before = client.get("/api/auth/me").json()["credits"]

    _upload(client, "Too short.")

    assert client.get("/api/auth/me").json()["credits"] == before


def test_a_long_enough_cv_is_accepted(client, monkeypatch):
    _login(client, monkeypatch)

    response = _upload(client, "Senior engineer. " * 40)

    assert response.status_code == 200


def test_the_minimum_follows_the_configured_value(client, monkeypatch):
    monkeypatch.setattr(settings, "cv_min_chars", 5000)
    _login(client, monkeypatch)

    # Comfortably over the default 200, still under the configured 5000.
    response = _upload(client, "Senior engineer. " * 40)

    assert response.status_code == 400

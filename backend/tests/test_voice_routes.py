"""Tests for the voice endpoints' auth and credit metering
(api/routes/voice.py). Same SQLite-backed TestClient approach as
test_sessions_routes.py — real login and real credit balances, with the
Deepgram calls stubbed out so nothing reaches a vendor.
"""
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from interview_bot.api.app import app
from interview_bot.api.routes import voice as voice_route
from interview_bot.config import settings
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
    Base.metadata.create_all(engine, tables=[User.__table__, UserSession.__table__])
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

    monkeypatch.setattr(schema_module, "initialize", lambda: None)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    app.dependency_overrides[database.get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, monkeypatch, *, sub: str = "sub-1", email: str = "jane@example.com") -> None:
    identity = google_auth.GoogleIdentity(sub=sub, email=email, name=None, picture=None)
    monkeypatch.setattr(google_auth, "verify", lambda token: identity)
    client.post("/api/auth/google", json={"id_token": "whatever"})


def _credits(client) -> int:
    return client.get("/api/auth/me").json()["credits"]


def _stub_synthesize(monkeypatch, result=b"audio-bytes") -> None:
    async def _fake(text: str) -> bytes:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(voice_route.speech, "synthesize", _fake)


def _stub_transcribe(monkeypatch, result="hello") -> None:
    async def _fake(audio: bytes, content_type: str) -> str:
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(voice_route.speech, "transcribe", _fake)


# --------------------------------------------------------------------------- #
# Authentication — both endpoints spend vendor money, so neither is anonymous
# --------------------------------------------------------------------------- #
def test_speak_requires_login(client):
    assert client.post("/api/speak", json={"text": "hello"}).status_code == 401


def test_transcribe_requires_login(client):
    response = client.post(
        "/api/transcribe", files={"audio": ("a.webm", b"bytes", "audio/webm")}
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# Credit metering
# --------------------------------------------------------------------------- #
def test_speak_does_not_debit_credits(client, monkeypatch):
    # Synthesis is paid for in the session's cost, not per request: a reply is
    # spoken as several requests as it streams, and the bill must not depend on
    # how the client split it.
    _login(client, monkeypatch)
    _stub_synthesize(monkeypatch)
    before = _credits(client)

    response = client.post("/api/speak", json={"text": "hello"})

    assert response.status_code == 200
    assert response.content == b"audio-bytes"
    assert _credits(client) == before


def test_speak_reports_a_vendor_failure_as_502(client, monkeypatch):
    _login(client, monkeypatch)
    _stub_synthesize(monkeypatch, result=RuntimeError("deepgram down"))
    before = _credits(client)

    assert client.post("/api/speak", json={"text": "hello"}).status_code == 502
    assert _credits(client) == before


def test_transcribe_debits_credits(client, monkeypatch):
    monkeypatch.setattr(settings, "transcription_credit_cost", 1)
    _login(client, monkeypatch)
    _stub_transcribe(monkeypatch)
    before = _credits(client)

    response = client.post(
        "/api/transcribe", files={"audio": ("a.webm", b"bytes", "audio/webm")}
    )

    assert response.status_code == 200
    assert response.json() == {"transcript": "hello"}
    assert _credits(client) == before - 1


def test_transcribe_refunds_credits_when_the_vendor_fails(client, monkeypatch):
    monkeypatch.setattr(settings, "transcription_credit_cost", 1)
    _login(client, monkeypatch)
    _stub_transcribe(monkeypatch, result=RuntimeError("deepgram down"))
    before = _credits(client)

    response = client.post(
        "/api/transcribe", files={"audio": ("a.webm", b"bytes", "audio/webm")}
    )

    assert response.status_code == 502
    assert _credits(client) == before


def test_transcribe_rejects_a_bad_upload_without_charging(client, monkeypatch):
    monkeypatch.setattr(settings, "transcription_credit_cost", 1)
    _login(client, monkeypatch)
    before = _credits(client)

    response = client.post(
        "/api/transcribe", files={"audio": ("a.pdf", b"bytes", "application/pdf")}
    )

    assert response.status_code == 415
    # Validation happens before the debit: a request the vendor never saw is free.
    assert _credits(client) == before


def test_speak_serves_a_caller_with_no_credits(client, monkeypatch):
    # Deliberate: the balance gates starting a session, and the session is where
    # synthesis is paid for. A signed-in caller with an empty balance can still
    # be spoken to; `TTS_CHARACTERS` is what bounds that per address.
    monkeypatch.setattr(settings, "signup_credit_grant", 0)
    _login(client, monkeypatch)
    _stub_synthesize(monkeypatch)

    assert client.post("/api/speak", json={"text": "hello"}).status_code == 200

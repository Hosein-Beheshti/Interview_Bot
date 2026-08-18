"""Tests for GET /api/config (api/routes/meta.py).

The endpoint exists so the browser does not keep its own copy of a limit. These
tests hold it to that: every field reports the live setting, and every field
corresponds to a setting that actually exists.
"""
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from interview_bot.api.app import app
from interview_bot.api.routes.meta import ClientConfig
from interview_bot.config import settings
from interview_bot.integrations import cv_parser
from interview_bot.persistence import schema as schema_module


@pytest.fixture
def client(monkeypatch) -> Iterator[TestClient]:
    # /config reads settings and nothing else, so there is no database to set up —
    # only the lifespan's schema call to neutralize.
    monkeypatch.setattr(schema_module, "initialize", lambda: None)
    with TestClient(app) as c:
        yield c


def test_config_reports_the_configured_values(client):
    body = client.get("/api/config").json()
    assert body["max_questions"] == settings.max_questions
    assert body["role_max_chars"] == settings.role_max_chars
    assert body["job_context_max_chars"] == settings.job_context_max_chars
    assert body["chat_message_max_chars"] == settings.chat_message_max_chars
    assert body["cv_max_bytes"] == settings.cv_max_bytes
    assert body["cv_min_chars"] == settings.cv_min_chars


def test_config_follows_a_changed_setting(monkeypatch, client):
    # The whole point: change the setting, the client sees the new value. A
    # captured constant would keep reporting the old one.
    monkeypatch.setattr(settings, "max_questions", 3)
    assert client.get("/api/config").json()["max_questions"] == 3


def test_accepted_extensions_match_the_parser_and_are_sorted(client):
    extensions = client.get("/api/config").json()["cv_accepted_extensions"]
    # Sourced from the parser, not restated — the client's file picker and the
    # server's `_validate_upload` must accept the same set.
    assert extensions == sorted(cv_parser.SUPPORTED_EXTENSIONS)
    assert extensions == sorted(extensions)


def test_every_published_field_names_a_real_setting():
    # A field here that is not a setting would be a number the client trusts and
    # nothing enforces. `cv_accepted_extensions` comes from the parser instead.
    for name in ClientConfig.model_fields:
        if name == "cv_accepted_extensions":
            continue
        assert hasattr(settings, name), name


def test_config_needs_no_authentication(client):
    # The browser needs these limits before login, on the sign-in screen.
    assert client.get("/api/config").status_code == 200

"""Tests for the CORS production-misconfig guard (config.py)."""
from types import SimpleNamespace

from interview_bot.config import is_dev_cors_in_production


def _settings(railway_environment: str, cors_origins: str):
    origins = [o.strip() for o in cors_origins.split(",") if o.strip()]
    return SimpleNamespace(
        railway_environment=railway_environment,
        cors_origins=cors_origins,
        cors_origin_list=origins,
    )


def test_not_on_railway_never_flags():
    s = _settings("", "http://localhost:5173,http://localhost:3000")
    assert not is_dev_cors_in_production(s)


def test_flags_dev_default_on_railway():
    s = _settings("production", "http://localhost:5173,http://localhost:3000")
    assert is_dev_cors_in_production(s)


def test_flags_wildcard_on_railway():
    s = _settings("production", "*")
    assert is_dev_cors_in_production(s)


def test_real_origin_on_railway_does_not_flag():
    s = _settings("production", "https://interview-bot.example.com")
    assert not is_dev_cors_in_production(s)

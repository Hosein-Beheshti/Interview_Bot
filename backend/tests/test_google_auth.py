"""Tests for Google ID-token verification (integrations/google_auth.py)."""
import pytest

from interview_bot.integrations import google_auth


def test_verify_maps_claims_to_identity(monkeypatch):
    claims = {
        "sub": "1234567890",
        "email": "jane@example.com",
        "name": "Jane Doe",
        "picture": "https://example.com/jane.jpg",
    }
    monkeypatch.setattr(
        google_auth.id_token, "verify_oauth2_token", lambda *a, **k: claims
    )

    identity = google_auth.verify("a-valid-token")

    assert identity == google_auth.GoogleIdentity(
        sub="1234567890",
        email="jane@example.com",
        name="Jane Doe",
        picture="https://example.com/jane.jpg",
    )


def test_verify_tolerates_missing_optional_claims(monkeypatch):
    claims = {"sub": "1234567890", "email": "jane@example.com"}
    monkeypatch.setattr(
        google_auth.id_token, "verify_oauth2_token", lambda *a, **k: claims
    )

    identity = google_auth.verify("a-valid-token")

    assert identity.name is None
    assert identity.picture is None


def test_verify_wraps_invalid_token_error(monkeypatch):
    def _reject(*args, **kwargs):
        raise ValueError("Token expired")

    monkeypatch.setattr(google_auth.id_token, "verify_oauth2_token", _reject)

    with pytest.raises(google_auth.GoogleTokenError, match="Token expired"):
        google_auth.verify("a-bad-token")

"""Google Identity Services ID-token verification.

Verification-only: no client secret, no token exchange, no refresh tokens. The
frontend obtains a Google ID token via Google Identity Services' JS SDK; this
module confirms it is genuine, unexpired, and issued for this app.
"""
from __future__ import annotations

from dataclasses import dataclass

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from interview_bot.config import settings
from interview_bot.logger import logger

_google_request = google_requests.Request()


class GoogleTokenError(Exception):
    """The presented ID token failed verification."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None
    picture: str | None


def verify(id_token_str: str) -> GoogleIdentity:
    """Verify a Google ID token and return the identity it carries.

    `verify_oauth2_token` checks the signature against Google's published
    certs, and issuer/expiry/audience (`settings.google_client_id`) — a token
    minted for a different app, or an expired or malformed one, raises here.
    """
    try:
        claims = id_token.verify_oauth2_token(
            id_token_str, _google_request, settings.google_client_id
        )
    except ValueError as e:
        logger.warning(f"Google ID token rejected | error={e}")
        raise GoogleTokenError(str(e)) from e
    return GoogleIdentity(
        sub=claims["sub"],
        email=claims["email"],
        name=claims.get("name"),
        picture=claims.get("picture"),
    )

"""PKCE helpers for OAuth 2.0 Authorization Code flow (RFC 7636)."""

from __future__ import annotations

import base64
import hashlib
import secrets

_MIN_VERIFIER_LENGTH = 43
_MAX_VERIFIER_LENGTH = 128


def generate_code_verifier() -> str:
    """Generate a high-entropy, URL-safe PKCE code verifier."""
    # 64 random bytes produce an 86-char base64url string (without padding),
    # which is within the RFC 7636 allowed 43-128 character range.
    verifier = (
        base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("ascii").rstrip("=")
    )
    if len(verifier) < _MIN_VERIFIER_LENGTH:
        verifier = verifier + ("A" * (_MIN_VERIFIER_LENGTH - len(verifier)))
    return verifier[:_MAX_VERIFIER_LENGTH]


def code_challenge_s256(verifier: str) -> str:
    """Create the S256 PKCE code challenge from a verifier."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

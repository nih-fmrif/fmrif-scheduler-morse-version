"""JWT verification helpers for Microsoft Entra tokens."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import jwt
import requests
from flask import current_app
from jwt import InvalidTokenError

from scheduler.config import normalize_email_address, settings

from .models import SessionUser


@dataclass
class _JWKSCache:
    """Simple in-memory cache for JWKS and discovery documents."""

    keys: List[Dict] | None = None
    keys_expiry: Optional[datetime] = None
    jwks_uri: Optional[str] = None
    discovery_expiry: Optional[datetime] = None

    def expired(self, expires_at: Optional[datetime]) -> bool:
        return not expires_at or datetime.utcnow() >= expires_at


_CACHE = _JWKSCache()


def _log_debug(message: str, *args: object) -> None:
    try:
        logger = getattr(current_app, "logger", None)
        if logger:
            if args:
                logger.debug(message, *args)
            else:
                logger.debug(message)
    except RuntimeError:
        # Outside of Flask app context; skip logging
        pass


def _log_warning(message: str, *args: object) -> None:
    try:
        logger = getattr(current_app, "logger", None)
        if logger:
            if args:
                logger.warning(message, *args)
            else:
                logger.warning(message)
    except RuntimeError:
        # Outside of Flask app context; skip logging
        pass


def _log_error(message: str, *args: object) -> None:
    try:
        logger = getattr(current_app, "logger", None)
        if logger:
            if args:
                logger.error(message, *args)
            else:
                logger.error(message)
    except RuntimeError:
        # Outside of Flask app context; skip logging
        pass


def _fetch_openid_configuration(discovery_url: str, cache_ttl: int) -> Dict:
    """Fetch OIDC discovery metadata and cache its JWKS URI."""
    if not discovery_url:
        raise ValueError("ENTRA discovery URL is not configured")

    if _CACHE.jwks_uri and not _CACHE.expired(_CACHE.discovery_expiry):
        return {"jwks_uri": _CACHE.jwks_uri}

    response = requests.get(discovery_url, timeout=5)
    response.raise_for_status()
    data = response.json()

    _CACHE.jwks_uri = data.get("jwks_uri")
    _CACHE.discovery_expiry = datetime.utcnow() + timedelta(seconds=cache_ttl)
    _log_debug("Refreshed Entra discovery configuration")
    return data


def _fetch_jwks(jwks_uri: str, cache_ttl: int) -> List[Dict]:
    """Fetch JWKS keys, caching them for the configured duration."""
    if _CACHE.keys and not _CACHE.expired(_CACHE.keys_expiry):
        return _CACHE.keys

    if not jwks_uri:
        raise ValueError("JWKS URI is not configured")

    response = requests.get(jwks_uri, timeout=5)
    response.raise_for_status()
    body = response.json()
    keys = body.get("keys", [])

    _CACHE.keys = keys
    _CACHE.keys_expiry = datetime.utcnow() + timedelta(seconds=cache_ttl)
    _log_debug("Refreshed Entra JWKS keys")
    return keys


def verify_jwt(
    token: str, *, audience: Optional[List[str]] = None
) -> Tuple[Optional[Dict], Optional[str]]:
    """Verify a JWT using Entra's JWKS keys.

    Returns a tuple of (claims, error_message). On success error_message is None.
    """

    config = settings.entra
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid:
            return None, "Missing kid in token header"
        alg = str(header.get("alg") or "").upper()
        allowed_algs = config.allowed_algorithms or ["RS256"]
        if alg not in allowed_algs:
            return None, f"Unsupported token signing algorithm: {alg or 'missing'}"

        discovery = _fetch_openid_configuration(
            config.discovery_url, cache_ttl=config.jwks_cache_ttl
        )
        jwks_uri = discovery.get("jwks_uri")
        keys = _fetch_jwks(jwks_uri, cache_ttl=config.jwks_cache_ttl)

        key_data = next((k for k in keys if k.get("kid") == kid), None)
        if not key_data:
            # refresh keys once to account for rotation
            keys = _fetch_jwks(jwks_uri, cache_ttl=0)
            key_data = next((k for k in keys if k.get("kid") == kid), None)
        if not key_data:
            return None, "Signing key not found for token"

        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))
        accepted_audiences = audience or config.audiences

        decoded = jwt.decode(
            token,
            public_key,
            algorithms=allowed_algs,
            audience=accepted_audiences or None,
            issuer=config.issuer or None,
            options={"verify_aud": bool(accepted_audiences)},
        )
        return decoded, None

    except (InvalidTokenError, requests.RequestException, ValueError) as exc:
        _log_debug(f"JWT verification failed: {exc}")
        return None, str(exc)


def user_from_claims(claims: Dict) -> SessionUser:
    """Convert validated JWT claims into a SessionUser model.

    Raises ValueError when required claims are missing.
    """
    if not claims:
        raise ValueError("JWT claims missing preferred_username")

    preferred_username_raw = str(claims.get("preferred_username") or "").strip().lower()
    if not preferred_username_raw:
        _log_warning(
            "JWT claims missing preferred_username; keys=%s", sorted(claims.keys())
        )
        raise ValueError("JWT claims missing preferred_username")
    try:
        preferred_username = str(
            normalize_email_address(
                preferred_username_raw, field_name="preferred_username"
            )
        ).lower()
    except ValueError:
        _log_error(
            "JWT preferred_username is not a valid email address; keys=%s",
            sorted(claims.keys()),
        )
        raise ValueError("JWT claims preferred_username is not a valid email address")

    # Import here to avoid importing scheduler.logic during module load.
    from scheduler.logic import scoped_user_id_from_identifier

    username = scoped_user_id_from_identifier(preferred_username)
    display_name = claims.get("name") or preferred_username
    groups = claims.get("groups") or []
    if isinstance(groups, str):
        groups = [groups]

    return SessionUser(
        username=username,
        email=preferred_username,
        display_name=display_name,
        groups=list(groups),
        claims=claims,
    )


def extract_bearer_token(auth_header: Optional[str]) -> Optional[str]:
    """Extract the raw JWT from an Authorization header."""
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    return auth_header.split(" ", 1)[1].strip()

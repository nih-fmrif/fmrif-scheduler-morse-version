"""OIDC discovery helpers for Entra authentication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

import requests
from flask import current_app

from scheduler.config import settings


@dataclass
class _DiscoveryCache:
    data: Optional[Dict] = None
    expires_at: Optional[datetime] = None

    def expired(self) -> bool:
        return not self.expires_at or datetime.utcnow() >= self.expires_at


_CACHE = _DiscoveryCache()


def _log_debug(message: str) -> None:
    try:
        logger = getattr(current_app, "logger", None)
        if logger:
            logger.debug(message)
    except RuntimeError:
        # Outside of Flask app context; skip logging
        pass


def fetch_oidc_metadata() -> Dict:
    """Fetch and cache OIDC discovery metadata."""
    if _CACHE.data and not _CACHE.expired():
        return _CACHE.data

    discovery_url = settings.entra.discovery_url
    if not discovery_url:
        raise ValueError("ENTRA discovery URL is not configured")

    response = requests.get(discovery_url, timeout=5)
    response.raise_for_status()
    data = response.json()

    ttl = settings.entra.jwks_cache_ttl or 3600
    _CACHE.data = data
    _CACHE.expires_at = datetime.utcnow() + timedelta(seconds=ttl)
    _log_debug("Refreshed Entra discovery configuration")
    return data


def get_authorization_endpoint() -> str:
    metadata = fetch_oidc_metadata()
    endpoint = metadata.get("authorization_endpoint")
    if endpoint:
        return endpoint
    if settings.entra.tenant_id:
        return (
            f"https://login.microsoftonline.com/{settings.entra.tenant_id}"
            "/oauth2/v2.0/authorize"
        )
    raise ValueError("authorization_endpoint not found in discovery metadata")


def get_token_endpoint() -> str:
    metadata = fetch_oidc_metadata()
    endpoint = metadata.get("token_endpoint")
    if endpoint:
        return endpoint
    if settings.entra.tenant_id:
        return (
            f"https://login.microsoftonline.com/{settings.entra.tenant_id}"
            "/oauth2/v2.0/token"
        )
    raise ValueError("token_endpoint not found in discovery metadata")

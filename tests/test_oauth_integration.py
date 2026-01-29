#!/usr/bin/env python3
"""
OAuth 2.0 Integration Tests
Tests basic OAuth endpoints without requiring a browser/Playwright runtime.
"""
import json
import os
import socket
import urllib.error
import urllib.request

import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5051")
TIMEOUT = 10


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _is_reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, socket.timeout, TimeoutError):
        return False


def _fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8")


@pytest.fixture(scope="session")
def base_url() -> str:
    probe_url = f"{BASE_URL}/auth/login"
    if not _is_reachable(probe_url):
        pytest.skip(f"BASE_URL not reachable: {BASE_URL}")
    return BASE_URL


def test_login_page_accessible(base_url):
    content = _fetch_text(f"{base_url}/auth/login")
    assert "Device Scheduler" in content
    assert "Sign in with your NIH credentials" in content


def test_entra_config_loads(base_url):
    config = json.loads(_fetch_text(f"{base_url}/api/config/entra.json"))

    required_fields = [
        "client_id",
        "tenant_id",
        "redirect_uri",
        "discovery_url",
    ]
    for field in required_fields:
        assert field in config
        assert config[field]

    assert config["redirect_uri"].startswith(("http://", "https://"))
    assert config["discovery_url"].startswith(("http://", "https://"))

    if config.get("authorization_endpoint"):
        assert config["authorization_endpoint"].startswith(("http://", "https://"))


def test_oauth_utils_available(base_url):
    files_to_check = {
        "/static/js/oauth-utils.js": ["generateVerifier", "pkceChallenge"],
        "/static/js/auth-manager.js": ["initializeAuth", "startOAuthFlow"],
    }

    for path, symbols in files_to_check.items():
        content = _fetch_text(f"{base_url}{path}")
        for symbol in symbols:
            assert symbol in content


def test_home_page_redirects(base_url):
    req = urllib.request.Request(f"{base_url}/", headers={"User-Agent": "Mozilla/5.0"})
    opener = urllib.request.build_opener(_NoRedirectHandler())

    try:
        with opener.open(req, timeout=TIMEOUT) as response:
            content = response.read().decode("utf-8")
            assert "Device Scheduler" in content or "logged in as superuser" in content
    except urllib.error.HTTPError as exc:
        assert exc.code in {302, 303, 307}


def test_callback_endpoint_exists(base_url):
    req = urllib.request.Request(f"{base_url}/auth/callback?code=test&state=test")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT):
            assert True
    except urllib.error.HTTPError as exc:
        assert 400 <= exc.code < 500

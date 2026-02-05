#!/usr/bin/env python3
"""
OAuth 2.0 Integration Tests (server-side flow)
Tests basic OAuth endpoints without requiring a browser/Playwright runtime.
"""
import os
import socket
import urllib.error
import urllib.request

import pytest

BASE_URL = os.environ.get("PLAYWRIGHT_BASE_URL") or os.environ.get(
    "BASE_URL", "http://localhost:5051"
)
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


def test_login_page_uses_server_side_flow(base_url):
    content = _fetch_text(f"{base_url}/auth/login")
    assert "/auth/entra" in content


def test_auth_start_redirects(base_url):
    opener = urllib.request.build_opener(_NoRedirectHandler())
    req = urllib.request.Request(f"{base_url}/auth/entra")

    try:
        with opener.open(req, timeout=TIMEOUT):
            assert False, "Expected redirect from /auth/entra"
    except urllib.error.HTTPError as exc:
        assert exc.code in {302, 303, 307}
        location = exc.headers.get("Location")
        assert location


def test_callback_requires_state(base_url):
    req = urllib.request.Request(f"{base_url}/auth/callback?code=test")
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(req, timeout=TIMEOUT):
            assert False, "Expected redirect due to missing state"
    except urllib.error.HTTPError as exc:
        assert exc.code in {302, 303, 307}

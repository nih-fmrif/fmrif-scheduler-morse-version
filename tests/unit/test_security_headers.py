import re

import pytest
from route_seed import (
    ensure_active_user,
    ensure_group,
    seeded_scanner_id,
    set_group_membership,
    set_session_user,
)

from scheduler.config import settings

pytestmark = pytest.mark.route


def test_security_headers_present_on_http(route_client):
    response = route_client.get("/auth/login")

    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    csp = response.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self' 'nonce-" in csp
    assert "'unsafe-inline'" not in csp
    assert "{nonce}" not in csp
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_present_on_https_requests(route_client):
    response = route_client.get(
        "/auth/login",
        environ_overrides={"wsgi.url_scheme": "https"},
    )
    assert response.headers.get("Strict-Transport-Security", "").startswith("max-age=")


def test_csp_report_only_mode(monkeypatch, route_client):
    monkeypatch.setattr(settings.security, "csp_report_only", True)
    response = route_client.get("/auth/login")
    assert "Content-Security-Policy" not in response.headers
    assert "Content-Security-Policy-Report-Only" in response.headers


def test_device_page_inline_style_nonce_matches_csp(route_client):
    ensure_group(
        "DEV",
        label="Development",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    ensure_active_user("nonce-route", "nonce-route@example.com", "Nonce Route")
    set_group_membership("DEV", "nonce-route", approved=True, pi=False)

    set_session_user(
        route_client,
        username="nonce-route",
        email="nonce-route@example.com",
        display_name="Nonce Route",
        groups=["DEV"],
    )
    response = route_client.get(f"/device/{seeded_scanner_id()}")

    assert response.status_code == 200

    csp = response.headers.get("Content-Security-Policy", "")
    csp_nonce_match = re.search(r"style-src[^;]*'nonce-([^']+)'", csp)
    assert csp_nonce_match is not None
    csp_nonce = csp_nonce_match.group(1)

    html = response.get_data(as_text=True)
    style_nonce_match = re.search(r"<style nonce=\"([^\"]+)\"", html)
    assert style_nonce_match is not None
    style_nonce = style_nonce_match.group(1)

    assert style_nonce
    assert style_nonce == csp_nonce

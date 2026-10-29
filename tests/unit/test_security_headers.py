import re

import pytest
from flask import jsonify, request
from route_seed import (
    ensure_active_user,
    ensure_group,
    seeded_scanner_id,
    set_group_membership,
    set_session_user,
)

from scheduler.config import settings

pytestmark = pytest.mark.route


def _script_nonce_from_csp(csp: str) -> str:
    match = re.search(r"script-src[^;]*'nonce-([^']+)'", csp)
    assert match is not None
    return match.group(1)


def test_security_headers_present_on_http(route_client):
    response = route_client.get("/auth/login")

    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    csp = response.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "'strict-dynamic'" in csp
    assert _script_nonce_from_csp(csp)
    assert "script-src-attr 'none'" in csp
    assert "style-src 'self'" in csp
    assert "style-src-attr 'none'" in csp
    assert "report-to csp-endpoint" in csp
    assert response.headers.get("Reporting-Endpoints") == 'csp-endpoint="/csp-report"'
    assert "'unsafe-inline'" not in csp
    assert "{nonce}" not in csp
    assert "Strict-Transport-Security" not in response.headers


def test_static_asset_urls_include_version_query(route_client):
    response = route_client.get("/auth/login")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert re.search(r"/static/base\.css\?v=[A-Za-z0-9]+", html)
    assert re.search(r"/static/js/theme-init\.js\?v=[A-Za-z0-9]+", html)


def test_login_page_scripts_use_header_nonce(route_client):
    response = route_client.get("/auth/login")

    assert response.status_code == 200

    csp = response.headers.get("Content-Security-Policy", "")
    nonce = _script_nonce_from_csp(csp)
    html = response.get_data(as_text=True)

    script_count = len(re.findall(r"<script\b", html))
    script_nonces = re.findall(r"<script\b[^>]*\bnonce=\"([^\"]+)\"", html)

    assert script_count > 0
    assert len(script_nonces) == script_count
    assert set(script_nonces) == {nonce}


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


def test_csp_nonce_placeholder_supported_for_custom_policy(monkeypatch, route_client):
    monkeypatch.setattr(
        settings.security,
        "csp_policy",
        "default-src 'self'; style-src 'self' 'nonce-{nonce}'",
    )
    response = route_client.get("/auth/login")

    csp = response.headers.get("Content-Security-Policy", "")
    nonce_match = re.search(r"style-src[^;]*'nonce-([^']+)'", csp)
    assert nonce_match is not None
    assert nonce_match.group(1)
    assert "report-to csp-endpoint" in csp
    assert response.headers.get("Reporting-Endpoints") == 'csp-endpoint="/csp-report"'
    assert "{nonce}" not in csp


def test_device_page_has_no_inline_style_markup(route_client):
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
    nonce = _script_nonce_from_csp(csp)
    html = response.get_data(as_text=True)
    assert "<style" not in html
    assert " style=" not in html
    script_count = len(re.findall(r"<script\b", html))
    script_nonces = re.findall(r"<script\b[^>]*\bnonce=\"([^\"]+)\"", html)
    assert script_count > 0
    assert len(script_nonces) == script_count
    assert set(script_nonces) == {nonce}


def test_device_page_includes_noscript_schedule_summary(route_client):
    ensure_group(
        "DEV",
        label="Development",
        description="Development Group",
        color="#222222",
        active=True,
        has_membership=True,
    )
    ensure_active_user(
        "noscript-route",
        "noscript-route@example.com",
        "Noscript Route",
    )
    set_group_membership("DEV", "noscript-route", approved=True, pi=False)

    set_session_user(
        route_client,
        username="noscript-route",
        email="noscript-route@example.com",
        display_name="Noscript Route",
        groups=["DEV"],
    )
    response = route_client.get(
        f"/device/{seeded_scanner_id()}?start=2024-01-01&days=3"
    )

    assert response.status_code == 200

    html = response.get_data(as_text=True)
    assert "<noscript>" in html
    assert "No JavaScript Fallback" in html
    assert "Read-only summary:" in html
    assert "from 2024-01-01 for 3" in html


def test_proxyfix_reconstructs_forwarded_scheme_host_and_port(monkeypatch):
    monkeypatch.setenv("MMSCHED_X_FORWARDED_FOR", "1")
    monkeypatch.setenv("MMSCHED_X_FORWARDED_PROTO", "1")
    monkeypatch.setenv("MMSCHED_X_FORWARDED_HOST", "1")
    monkeypatch.setenv("MMSCHED_X_FORWARDED_PORT", "1")

    from scheduler.app import create_app

    app = create_app()

    @app.get("/__proxy-metadata")
    def proxy_metadata():
        return jsonify(
            {
                "host": request.host,
                "scheme": request.scheme,
                "is_secure": request.is_secure,
                "url_root": request.url_root,
            }
        )

    with app.test_client() as client:
        response = client.get(
            "/__proxy-metadata",
            headers={
                "Host": "scheduler.internal:5051",
                "X-Forwarded-For": "198.51.100.77",
                "X-Forwarded-Host": "proxy.example.test",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Port": "8443",
            },
        )

    assert response.status_code == 200
    assert response.headers.get("Strict-Transport-Security", "").startswith("max-age=")

    csp = response.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "'strict-dynamic'" in csp
    assert _script_nonce_from_csp(csp)
    assert "script-src-attr 'none'" in csp
    assert "style-src 'self'" in csp
    assert "style-src-attr 'none'" in csp
    assert "report-to csp-endpoint" in csp
    assert response.headers.get("Reporting-Endpoints") == 'csp-endpoint="/csp-report"'

    payload = response.get_json()
    assert payload == {
        "host": "proxy.example.test:8443",
        "scheme": "https",
        "is_secure": True,
        "url_root": "https://proxy.example.test:8443/",
    }

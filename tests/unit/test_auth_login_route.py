import re

import pytest

pytestmark = pytest.mark.route


def _extract_login_link_href(html: str) -> str:
    match = re.search(
        r'<a\b(?=[^>]*\bid="login-btn")(?=[^>]*\bhref="([^"]+)")[^>]*>',
        html,
    )
    assert match is not None
    return match.group(1)


def test_home_redirects_html_clients_to_login_when_unauthenticated(route_client):
    response = route_client.get(
        "/",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers.get("Location", "").endswith("/auth/login")


def test_login_preserves_safe_relative_next_targets(route_client):
    response = route_client.get("/auth/login?next=%2Fdevices")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    href = _extract_login_link_href(html)
    assert href.endswith("/auth/entra?next=%2Fdevices")
    assert "<form" not in html


def test_login_drops_unsafe_absolute_next_targets(route_client):
    response = route_client.get("/auth/login?next=https%3A%2F%2Fevil.example")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    href = _extract_login_link_href(html)
    assert href.endswith("/auth/entra")
    assert "<form" not in html

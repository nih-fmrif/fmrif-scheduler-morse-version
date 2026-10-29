import re

import pytest

pytestmark = pytest.mark.route


def _extract_login_form_action(html: str) -> str:
    match = re.search(r'<form[^>]*action="([^"]+)"', html)
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
    action = _extract_login_form_action(response.get_data(as_text=True))
    assert action.endswith("/auth/entra?next=%2Fdevices")


def test_login_drops_unsafe_absolute_next_targets(route_client):
    response = route_client.get("/auth/login?next=https%3A%2F%2Fevil.example")

    assert response.status_code == 200
    action = _extract_login_form_action(response.get_data(as_text=True))
    assert action.endswith("/auth/entra")

import pytest
from flask.sessions import SecureCookieSessionInterface
from route_seed import extract_csrf_token, set_session_user

pytestmark = pytest.mark.route


def test_logout_get_is_not_allowed(monkeypatch, route_app, route_client):
    monkeypatch.setattr(route_app, "session_interface", SecureCookieSessionInterface())

    response = route_client.get("/auth/logout")
    assert response.status_code == 405


@pytest.mark.covers_route("/auth/logout", "POST")
def test_logout_post_requires_valid_csrf(monkeypatch, route_app, route_client):
    monkeypatch.setattr(route_app, "session_interface", SecureCookieSessionInterface())

    set_session_user(
        route_client,
        username="logout-user",
        email="logout-user@example.com",
        display_name="Logout User",
    )
    response = route_client.post("/auth/logout", data={})

    assert response.status_code == 400
    with route_client.session_transaction() as sess:
        assert sess.get("user_name") == "logout-user"


def test_logout_post_valid_csrf_logs_out(monkeypatch, route_app, route_client):
    monkeypatch.setattr(route_app, "session_interface", SecureCookieSessionInterface())
    set_session_user(
        route_client,
        username="logout-user",
        email="logout-user@example.com",
        display_name="Logout User",
    )
    home_response = route_client.get("/")
    csrf_token = extract_csrf_token(home_response.get_data(as_text=True))

    response = route_client.post(
        "/auth/logout",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    with route_client.session_transaction() as sess:
        assert sess.get("user_name") is None
        assert sess.get("email") is None

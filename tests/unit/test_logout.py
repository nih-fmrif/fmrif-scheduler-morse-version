import pytest
from flask.sessions import SecureCookieSessionInterface
from route_seed import extract_csrf_token, set_session_user

from scheduler.app import app

pytestmark = pytest.mark.route


def test_logout_get_is_not_allowed(monkeypatch):
    monkeypatch.setattr(app, "session_interface", SecureCookieSessionInterface())
    client = app.test_client()

    response = client.get("/auth/logout")
    assert response.status_code == 405


@pytest.mark.covers_route("/auth/logout", "POST")
def test_logout_post_requires_valid_csrf(monkeypatch):
    monkeypatch.setattr(app, "session_interface", SecureCookieSessionInterface())

    client = app.test_client()
    set_session_user(
        client,
        username="logout-user",
        email="logout-user@example.com",
        display_name="Logout User",
    )
    response = client.post("/auth/logout", data={})

    assert response.status_code == 400
    with client.session_transaction() as sess:
        assert sess.get("user_name") == "logout-user"


def test_logout_post_valid_csrf_logs_out(monkeypatch):
    monkeypatch.setattr(app, "session_interface", SecureCookieSessionInterface())
    client = app.test_client()
    set_session_user(
        client,
        username="logout-user",
        email="logout-user@example.com",
        display_name="Logout User",
    )
    home_response = client.get("/")
    csrf_token = extract_csrf_token(home_response.get_data(as_text=True))

    response = client.post(
        "/auth/logout",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")
    with client.session_transaction() as sess:
        assert sess.get("user_name") is None
        assert sess.get("email") is None
